# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Creates and removes the recurring job that runs main.py.

Task Scheduler on Windows, crontab everywhere else.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "CloudflareDNSSync"
CRON_MARKER = "# cf-dns-sync"

IS_WINDOWS = os.name == "nt"


class ScheduleError(Exception):
    """The system scheduler refused a create or delete."""


def cron_schedule(minutes: int) -> str:
    """Turn an interval in minutes into the five cron timing fields."""
    if minutes < 1:
        # 0 would otherwise fall through to the hourly branch and emit "0 */0 * * *".
        raise ScheduleError("the interval must be at least 1 minute")
    if minutes < 60:
        return f"*/{minutes} * * * *"
    if minutes == 60:
        return "0 * * * *"
    if minutes == 1440:
        return "0 0 * * *"
    if minutes % 60 == 0 and minutes < 1440:
        return f"0 */{minutes // 60} * * *"
    raise ScheduleError(
        f"cannot express every {minutes} minutes as a cron schedule. "
        "Use 1-59, or a whole number of hours up to 24."
    )


def cron_line(python: Path, script: Path, minutes: int) -> str:
    return f"{cron_schedule(minutes)} {python} {script} {CRON_MARKER}"


def _run(command: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, input=stdin, capture_output=True, text=True, check=False
    )


# --- crontab ---------------------------------------------------------------

def _read_crontab() -> list[str]:
    result = _run(["crontab", "-l"])
    if result.returncode != 0:  # no crontab yet is not an error
        return []
    return result.stdout.splitlines()


def _write_crontab(lines: list[str]) -> None:
    body = "\n".join(lines).strip("\n")
    result = _run(["crontab", "-"], stdin=body + "\n" if body else "\n")
    if result.returncode != 0:
        raise ScheduleError(f"crontab refused the update: {result.stderr.strip()}")


def _without_ours(lines: list[str]) -> list[str]:
    return [line for line in lines if CRON_MARKER not in line]


# --- Task Scheduler --------------------------------------------------------

def _windows_runner(python: Path) -> Path:
    """Prefer pythonw.exe so the task doesn't flash a console window."""
    windowless = python.with_name("pythonw.exe")
    return windowless if windowless.is_file() else python


# --- public API ------------------------------------------------------------

def install(python: Path, script: Path, minutes: int) -> str:
    """(Re)create the recurring job. Returns a human-readable description."""
    python, script = Path(python).resolve(), Path(script).resolve()

    if IS_WINDOWS:
        runner = _windows_runner(python)
        result = _run([
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", f'"{runner}" "{script}"',
            "/SC", "MINUTE",
            "/MO", str(minutes),
            "/F",
        ])
        if result.returncode != 0:
            raise ScheduleError(
                f"schtasks could not create the task: {(result.stderr or result.stdout).strip()}"
            )
        return f'Task Scheduler task "{TASK_NAME}", every {minutes} minute(s)'

    line = cron_line(python, script, minutes)
    _write_crontab(_without_ours(_read_crontab()) + [line])
    return f"crontab entry: {line}"


def uninstall() -> bool:
    """Remove the recurring job. Returns True if one was actually there."""
    if IS_WINDOWS:
        if not is_installed():
            return False
        result = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        if result.returncode != 0:
            raise ScheduleError(
                f"schtasks could not delete the task: {(result.stderr or result.stdout).strip()}"
            )
        return True

    existing = _read_crontab()
    remaining = _without_ours(existing)
    if len(remaining) == len(existing):
        return False
    _write_crontab(remaining)
    return True


def is_installed() -> bool:
    if IS_WINDOWS:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
    return any(CRON_MARKER in line for line in _read_crontab())
