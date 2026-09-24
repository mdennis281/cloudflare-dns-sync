import logging
import os
import time
from datetime import date, timedelta

import pytest

from cfdns.logfile import DAILY, OFF, SIZE, RotatingLogHandler, archives, leftovers


def handler(path, **kwargs):
    handle = RotatingLogHandler(path, **kwargs)
    handle.setFormatter(logging.Formatter("%(message)s"))
    return handle


def write(handle, message):
    handle.handle(
        logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    )


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def backdate(path, days=1):
    """Make the log look like it was last written to `days` ago."""
    when = time.time() - days * 86400
    os.utime(path, (when, when))


@pytest.fixture
def log(tmp_path):
    return tmp_path / "CF-DNS.log"


# --- size rotation ----------------------------------------------------------

def test_writes_without_rotating_while_under_the_ceiling(log):
    handle = handler(log, mode=SIZE, max_size=1024)
    write(handle, "first")
    write(handle, "second")
    handle.close()

    assert lines(log) == ["first", "second"]
    assert archives(log) == []


def test_rotates_when_the_next_line_would_cross_the_ceiling(log):
    handle = handler(log, mode=SIZE, max_size=32, backups=3)
    write(handle, "a" * 20)
    write(handle, "b" * 20)
    handle.close()

    rotated = log.with_name("CF-DNS.log.1")
    assert lines(rotated) == ["a" * 20]
    assert lines(log) == ["b" * 20]


def test_max_size_is_a_real_ceiling_not_a_threshold(log):
    handle = handler(log, mode=SIZE, max_size=64, backups=3)
    for index in range(20):
        write(handle, f"line {index} " + "x" * 20)
    handle.close()

    assert log.stat().st_size <= 64
    for rotated in archives(log):
        assert rotated.stat().st_size <= 64


def test_keeps_only_the_configured_number_of_backups(log):
    handle = handler(log, mode=SIZE, max_size=32, backups=2)
    for index in range(10):
        write(handle, f"message {index} " + "x" * 20)
    handle.close()

    assert [p.name for p in archives(log)] == ["CF-DNS.log.1", "CF-DNS.log.2"]


def test_backups_shift_down_so_dot_one_is_always_the_newest(log):
    handle = handler(log, mode=SIZE, max_size=12, backups=3)  # one word per file
    for word in ("oldest", "middle", "newest", "current"):
        write(handle, word)
    handle.close()

    assert lines(log.with_name("CF-DNS.log.1")) == ["newest"]
    assert lines(log.with_name("CF-DNS.log.2")) == ["middle"]
    assert lines(log.with_name("CF-DNS.log.3")) == ["oldest"]
    assert lines(log) == ["current"]


def test_zero_backups_discards_the_old_log(log):
    handle = handler(log, mode=SIZE, max_size=16, backups=0)
    write(handle, "thrown away")
    write(handle, "kept")
    handle.close()

    assert lines(log) == ["kept"]
    assert archives(log) == []


def test_an_empty_log_is_never_rotated(log):
    log.write_text("", encoding="utf-8")
    handle = handler(log, mode=SIZE, max_size=1024)
    write(handle, "first line")
    handle.close()

    assert lines(log) == ["first line"]
    assert archives(log) == []


# --- daily rotation ---------------------------------------------------------

def test_rotates_once_the_file_is_a_day_old(log):
    handle = handler(log, mode=DAILY)
    write(handle, "yesterday")
    backdate(log)
    write(handle, "today")
    handle.close()

    yesterday = date.today() - timedelta(days=1)
    assert lines(log.with_name(f"CF-DNS.log.{yesterday.isoformat()}")) == ["yesterday"]
    assert lines(log) == ["today"]


def test_daily_leaves_a_log_written_the_same_day_alone(log):
    handle = handler(log, mode=DAILY)
    write(handle, "morning")
    write(handle, "afternoon")
    handle.close()

    assert lines(log) == ["morning", "afternoon"]
    assert archives(log) == []


def test_daily_keeps_only_the_newest_archives(log):
    for age in range(2, 6):  # four archives already on disk, oldest first
        stamp = (date.today() - timedelta(days=age)).isoformat()
        log.with_name(f"CF-DNS.log.{stamp}").write_text("old\n", encoding="utf-8")

    handle = handler(log, mode=DAILY, backups=2)
    write(handle, "yesterday")
    backdate(log)
    write(handle, "today")
    handle.close()

    kept = [p.name for p in archives(log)]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days = (date.today() - timedelta(days=2)).isoformat()
    assert kept == [f"CF-DNS.log.{two_days}", f"CF-DNS.log.{yesterday}"]


def test_daily_does_not_clobber_an_archive_from_the_same_day(log):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    existing = log.with_name(f"CF-DNS.log.{yesterday}")
    existing.write_text("already archived\n", encoding="utf-8")

    handle = handler(log, mode=DAILY, backups=5)
    write(handle, "second run")
    backdate(log)
    write(handle, "today")
    handle.close()

    assert lines(existing) == ["already archived"]
    assert lines(log.with_name(f"CF-DNS.log.{yesterday}.1")) == ["second run"]


# --- off --------------------------------------------------------------------

def test_off_never_rotates_however_big_it_gets(log):
    handle = handler(log, mode=OFF, max_size=16)
    for index in range(10):
        write(handle, f"line {index}")
    backdate(log)
    write(handle, "still here")
    handle.close()

    assert archives(log) == []
    assert len(lines(log)) == 11


def test_an_unknown_mode_is_rejected(log):
    with pytest.raises(ValueError, match="unknown rotation mode"):
        RotatingLogHandler(log, mode="hourly")


# --- sharing the file between processes -------------------------------------

def test_two_writers_on_one_file_lose_nothing(log):
    """Two handlers stand in for the overlapping cron/Task Scheduler runs.

    Each rotation is decided inside the lock and against the file on disk, so
    neither writer can rotate a file the other already rotated, and neither
    ends up appending to a path that no longer exists.
    """
    first = handler(log, mode=SIZE, max_size=64, backups=20)
    second = handler(log, mode=SIZE, max_size=64, backups=20)

    for index in range(15):
        write(first, f"first-{index:02d}")
        write(second, f"second-{index:02d}")
    first.close()
    second.close()

    written = []
    for path in [log, *archives(log)]:
        written += lines(path)
    for index in range(15):
        assert f"first-{index:02d}" in written
        assert f"second-{index:02d}" in written


def test_a_second_writer_picks_up_the_new_file_after_a_rotation(log):
    first = handler(log, mode=SIZE, max_size=32, backups=3)
    second = handler(log, mode=SIZE, max_size=32, backups=3)

    write(first, "x" * 20)
    write(second, "y" * 20)  # this one rotates
    write(first, "z")  # ...and this must land in the new file, not the archive

    first.close()
    second.close()
    assert lines(log) == ["y" * 20, "z"]


# --- archives() -------------------------------------------------------------

ROTATED = (
    "CF-DNS.log.1",
    "CF-DNS.log.12",
    "CF-DNS.log.2026-08-21",
    "CF-DNS.log.2026-08-21.1",
)
UNRELATED = ("CF-DNS.log.bak", "other.log", "other.log.1", "CF-DNS.txt")


def populate(log):
    log.write_text("live\n", encoding="utf-8")
    for name in ROTATED + UNRELATED + ("CF-DNS.log.lock",):
        log.with_name(name).write_text("", encoding="utf-8")


def test_archives_finds_the_rotated_copies_and_nothing_else(log):
    populate(log)
    assert [p.name for p in archives(log)] == list(ROTATED)


def test_leftovers_also_claims_the_lock_file(log):
    populate(log)
    assert [p.name for p in leftovers(log)] == [*ROTATED, "CF-DNS.log.lock"]


def test_nothing_to_find_for_a_log_that_was_never_written(tmp_path):
    assert archives(tmp_path / "nothing-here.log") == []
    assert leftovers(tmp_path / "nothing-here.log") == []


def test_nothing_to_find_in_a_directory_that_does_not_exist(tmp_path):
    assert archives(tmp_path / "gone" / "CF-DNS.log") == []
    assert leftovers(tmp_path / "gone" / "CF-DNS.log") == []
