# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""A rotating log handler that stays correct when processes share the file.

The sync runs from cron or Task Scheduler, so a slow run and the next one can
overlap and both want the same log file. Python's stock ``RotatingFileHandler``
assumes it is the only writer, and that assumption breaks differently on each
platform: on Linux the process that loses the race keeps writing to a file that
has already been renamed out from under it, and on Windows the rename itself
fails with "used by another process" because the other side still has the file
open. Neither is loud about it -- you just quietly lose log lines.

So this handler serializes the whole open-write-close cycle behind an advisory
lock on a sidecar ``<log>.lock`` file (``flock`` on POSIX, ``msvcrt`` on
Windows), and re-checks the file's size inside the lock, so two processes that
both decide to rotate only rotate once. The file is opened per record rather
than held open: that costs a syscall in a program that writes a handful of
lines every few minutes, and it means nobody is sitting on a handle that would
block someone else's rotation.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX has no msvcrt
    msvcrt = None


SIZE = "size"
DAILY = "daily"
OFF = "off"
MODES = (SIZE, DAILY, OFF)

DEFAULT_MAX_SIZE = 1024 * 1024  # 1 MB
DEFAULT_BACKUPS = 5

LOCK_SUFFIX = ".lock"

# Rotation leaves CF-DNS.log.3 (size) or CF-DNS.log.2026-08-21 (daily), plus
# CF-DNS.log.2026-08-21.1 when a day gets archived twice.
_DATED_SUFFIX = r"\d{4}-\d{2}-\d{2}(?:\.\d+)?"
_ARCHIVE_SUFFIX = rf"(?:\d+|{_DATED_SUFFIX})"


class _CrossProcessLock:
    """An exclusive advisory lock held on a sidecar file.

    Best effort on purpose: a filesystem that cannot lock (some network
    mounts) or a permissions problem must not cost us a log line, so a failed
    lock degrades to an unlocked write instead of raising. Appends stay atomic
    either way; only rotation loses its guarantee.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd = None
        self._held = False

    def __enter__(self) -> "_CrossProcessLock":
        self._held = False
        try:
            if self._fd is None:
                self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_EX)
            elif msvcrt is not None:
                # LK_LOCK blocks, retrying for ~10s, then raises. One byte is
                # enough: every writer agrees to lock byte 0 and nothing else.
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
            self._held = True
        except OSError:
            self._held = False
        return self

    def __exit__(self, *exc_info: object) -> bool:
        if self._held and self._fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                elif msvcrt is not None:
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._held = False
        return False

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None


class RotatingLogHandler(logging.Handler):
    """Append to ``path``, rotating it by size or by day.

    ``mode`` is one of ``size`` (``CF-DNS.log.1`` ... ``.N``, oldest dropped),
    ``daily`` (``CF-DNS.log.2026-08-21``, oldest dropped), or ``off``.
    ``backups`` of 0 means "rotate by throwing the old content away".
    """

    # Match the stock FileHandler: native line endings, so a Windows log still
    # opens cleanly in whatever editor the user reaches for.
    terminator = os.linesep

    def __init__(
        self,
        path: str | os.PathLike[str],
        mode: str = SIZE,
        max_size: int = DEFAULT_MAX_SIZE,
        backups: int = DEFAULT_BACKUPS,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        if mode not in MODES:
            raise ValueError(f"unknown rotation mode {mode!r}; use one of {', '.join(MODES)}")
        self.path = Path(path)
        self.mode = mode
        self.max_size = max(0, int(max_size))
        self.backups = max(0, int(backups))
        self.encoding = encoding
        self._lock_file = _CrossProcessLock(self.path.with_name(self.path.name + LOCK_SUFFIX))

    # --- logging.Handler ---------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record) + self.terminator
            # backslashreplace: a stray byte in a hostname should mangle one
            # word, not throw the whole message away.
            data = line.encode(self.encoding, errors="backslashreplace")
            with self._lock_file:
                self._rotate_if_needed(len(data))
                with open(self.path, "ab") as stream:
                    stream.write(data)
        except Exception:  # logging must never take the sync down with it
            self.handleError(record)

    def close(self) -> None:
        try:
            self._lock_file.close()
        finally:
            super().close()

    # --- rotation ----------------------------------------------------------

    def _rotate_if_needed(self, incoming: int) -> None:
        """Called holding the lock, which is what makes this stat worth trusting."""
        if self.mode == OFF:
            return
        try:
            info = self.path.stat()
        except OSError:  # not there yet, or unreadable -- let the append decide
            return
        if not info.st_size:  # never rotate an empty file
            return

        if self.mode == SIZE:
            # Rotate *before* the write that would cross the line, so max_size
            # is a real ceiling rather than a threshold we always overshoot.
            if self.max_size and info.st_size + incoming > self.max_size:
                self._rotate_numbered()
        elif self.mode == DAILY:
            # The day comes from the file, not from a rollover time we worked
            # out at startup: this process may only be a few seconds old.
            written = datetime.fromtimestamp(info.st_mtime).date()
            if written < date.today():
                self._rotate_dated(written)

    def _rotate_numbered(self) -> None:
        if not self.backups:
            self.path.unlink(missing_ok=True)
            return

        self._numbered(self.backups).unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self._numbered(index)
            if source.exists():
                os.replace(source, self._numbered(index + 1))
        os.replace(self.path, self._numbered(1))

    def _numbered(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.name}.{index}")

    def _rotate_dated(self, day: date) -> None:
        if not self.backups:
            self.path.unlink(missing_ok=True)
            return

        target = self.path.with_name(f"{self.path.name}.{day.isoformat()}")
        attempt = 1
        while target.exists():  # clock went backwards; don't clobber the archive
            target = self.path.with_name(f"{self.path.name}.{day.isoformat()}.{attempt}")
            attempt += 1
        os.replace(self.path, target)
        self._prune_dated()

    def _prune_dated(self) -> None:
        dated = re.compile(rf"{re.escape(self.path.name)}\.{_DATED_SUFFIX}")
        # ISO dates sort chronologically, so plain sorting puts the oldest first.
        existing = sorted(p for p in archives(self.path) if dated.fullmatch(p.name))
        for stale in existing[: max(0, len(existing) - self.backups)]:
            stale.unlink(missing_ok=True)


def archives(path: str | os.PathLike[str]) -> list[Path]:
    """The rotated copies of ``path``, oldest naming first."""
    return _matching(Path(path), _ARCHIVE_SUFFIX)


def leftovers(path: str | os.PathLike[str]) -> list[Path]:
    """Every file this handler may have left beside ``path``, lock included.

    The uninstaller uses this so that cleaning up doesn't mean re-deriving our
    naming scheme somewhere else and getting it subtly wrong.
    """
    return _matching(Path(path), rf"(?:{_ARCHIVE_SUFFIX}|{re.escape(LOCK_SUFFIX[1:])})")


def _matching(path: Path, suffix_pattern: str) -> list[Path]:
    pattern = re.compile(rf"{re.escape(path.name)}\.{suffix_pattern}")
    try:
        entries = list(path.parent.iterdir())
    except OSError:
        return []
    return sorted(p for p in entries if pattern.fullmatch(p.name) and p.is_file())
