from pathlib import PurePosixPath

import pytest

from cfdns import schedule
from cfdns.schedule import CRON_MARKER, ScheduleError, cron_line, cron_schedule


@pytest.mark.parametrize(
    "minutes, expected",
    [
        (1, "*/1 * * * *"),
        (5, "*/5 * * * *"),
        (10, "*/10 * * * *"),
        (30, "*/30 * * * *"),
        (59, "*/59 * * * *"),
        (60, "0 * * * *"),
        (120, "0 */2 * * *"),
        (720, "0 */12 * * *"),
        (1440, "0 0 * * *"),
    ],
)
def test_cron_schedule(minutes, expected):
    assert cron_schedule(minutes) == expected


@pytest.mark.parametrize("minutes", [0, -5, 90, 100, 1500])
def test_cron_schedule_rejects_intervals_it_cannot_express(minutes):
    with pytest.raises(ScheduleError):
        cron_schedule(minutes)


def test_cron_line_is_marked_so_uninstall_can_find_it():
    line = cron_line(PurePosixPath("/app/.venv/bin/python"), PurePosixPath("/app/main.py"), 10)
    assert line == f"*/10 * * * * /app/.venv/bin/python /app/main.py {CRON_MARKER}"
    assert CRON_MARKER in line


def test_uninstall_only_strips_our_own_crontab_lines(monkeypatch):
    existing = [
        "0 3 * * * /usr/bin/backup.sh",
        f"*/10 * * * * /app/.venv/bin/python /app/main.py {CRON_MARKER}",
        "@reboot /usr/bin/something-else",
    ]
    written = []

    monkeypatch.setattr(schedule, "IS_WINDOWS", False)
    monkeypatch.setattr(schedule, "_read_crontab", lambda: existing)
    monkeypatch.setattr(schedule, "_write_crontab", written.append)

    assert schedule.uninstall() is True
    assert written == [[existing[0], existing[2]]]


def test_uninstall_reports_false_when_nothing_was_installed(monkeypatch):
    monkeypatch.setattr(schedule, "IS_WINDOWS", False)
    monkeypatch.setattr(schedule, "_read_crontab", lambda: ["0 3 * * * /usr/bin/backup.sh"])
    monkeypatch.setattr(
        schedule, "_write_crontab", lambda lines: pytest.fail("must not rewrite the crontab")
    )

    assert schedule.uninstall() is False


def test_install_replaces_a_previous_entry_rather_than_stacking(monkeypatch, tmp_path):
    existing = [
        "0 3 * * * /usr/bin/backup.sh",
        f"*/30 * * * * /old/python /old/main.py {CRON_MARKER}",
    ]
    written = []

    monkeypatch.setattr(schedule, "IS_WINDOWS", False)
    monkeypatch.setattr(schedule, "_read_crontab", lambda: existing)
    monkeypatch.setattr(schedule, "_write_crontab", written.append)

    schedule.install(tmp_path / "python", tmp_path / "main.py", 10)

    lines = written[0]
    assert sum(CRON_MARKER in line for line in lines) == 1
    assert lines[0] == "0 3 * * * /usr/bin/backup.sh"
