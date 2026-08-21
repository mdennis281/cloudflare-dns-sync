#!/usr/bin/env python3
# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/Python-Cloudflare-DNS-External-IP-Synchronizer
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Interactive setup: verify an API token, pick a schedule, write config.ini.

Normally launched by setup.sh / setup.ps1, which build the venv first.
Removing the venv is those scripts' job, not this one's -- on Windows a
running interpreter cannot delete the venv it lives in.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import sys
from configparser import ConfigParser
from pathlib import Path

from cfdns import schedule
from cfdns.cloudflare import Cloudflare, CloudflareError

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.ini"
EXAMPLE = ROOT / "config.example.ini"

FREQUENCIES = [
    ("every 5 minutes", 5),
    ("every 10 minutes", 10),
    ("every 15 minutes", 15),
    ("every 30 minutes", 30),
    ("every hour", 60),
    ("custom", None),
    ("don't schedule it - I'll run it myself", 0),
]


def say(message: str = "") -> None:
    print(message)


def ask(prompt: str, default: str = "") -> str:
    if not sys.stdin.isatty():
        raise SystemExit("install.py needs an interactive terminal.")
    return input(prompt).strip() or default


def confirm(prompt: str, default: bool = False) -> bool:
    if not sys.stdin.isatty():
        return default
    answer = input(prompt + (" [Y/n] " if default else " [y/N] ")).strip().lower()
    return default if not answer else answer.startswith("y")


# --- config.ini editing -----------------------------------------------------

def set_ini_values(text: str, section: str, values: dict[str, str]) -> str:
    """Set `key = value` inside one ini section, keeping comments intact.

    ConfigParser would round-trip the file and throw the comments away, and
    those comments are the documentation the user reads next.
    """
    out: list[str] = []
    current = None
    seen: set[str] = set()
    insert_at = None
    wanted = {key.lower(): key for key in values}

    for line in text.splitlines():
        header = re.match(r"\s*\[(?P<name>[^\]]+)\]\s*$", line)
        if header:
            if current == section and insert_at is None:
                insert_at = len(out)
            current = header.group("name")
            out.append(line)
            continue

        if current == section:
            match = re.match(r"(?P<indent>\s*)(?P<key>[A-Za-z_][\w-]*)\s*=", line)
            if match and match.group("key").lower() in wanted:
                key = wanted[match.group("key").lower()]
                out.append(f"{match.group('indent')}{key} = {values[key]}")
                seen.add(key)
                continue
        out.append(line)

    if current == section and insert_at is None:
        insert_at = len(out)

    missing = [f"{key} = {value}" for key, value in values.items() if key not in seen]
    if missing:
        if insert_at is None:  # section absent entirely
            out += ["", f"[{section}]", *missing]
        else:
            out[insert_at:insert_at] = missing

    return "\n".join(out) + "\n"


def write_config(token: str, site_name: str) -> None:
    if not CONFIG.exists():
        if not EXAMPLE.exists():
            raise SystemExit(f"missing {EXAMPLE.name}; cannot create config.ini")
        shutil.copyfile(EXAMPLE, CONFIG)
        say(f"  created {CONFIG.name} from {EXAMPLE.name}")

    values = {"token": token}
    if site_name:
        values["siteName"] = site_name
    CONFIG.write_text(
        set_ini_values(CONFIG.read_text(encoding="utf-8"), "CloudFlare-API", values),
        encoding="utf-8",
    )
    if os.name != "nt":  # the file holds an API token
        CONFIG.chmod(0o600)


# --- interactive steps ------------------------------------------------------

def prompt_token() -> tuple[str, Cloudflare]:
    say("Create a token at https://dash.cloudflare.com/profile/api-tokens")
    say("It needs two permissions:  Zone > Zone > Read   and   Zone > DNS > Edit")
    say()

    while True:
        token = getpass.getpass("Cloudflare API token (hidden): ").strip()
        if not token:
            if confirm("No token entered. Give up?"):
                raise SystemExit(1)
            continue

        api = Cloudflare(token)
        try:
            result = api.verify_token()
        except CloudflareError as err:
            api.close()
            say(f"  that token didn't work: {err}")
            say()
            continue

        status = (result or {}).get("status")
        if status != "active":
            api.close()
            say(f"  that token is not active (status: {status})")
            continue

        say("  token verified")
        return token, api


def prompt_zone(api: Cloudflare) -> str:
    try:
        zones = api.zones()
    except CloudflareError as err:
        say(f"  could not list zones ({err}); leaving siteName blank")
        return ""

    if not zones:
        say("  this token can't see any zones. Check its Zone > Zone > Read permission.")
        return ""
    if len(zones) == 1:
        say(f"  default zone: {zones[0]['name']}")
        return str(zones[0]["name"])

    say()
    say("Which zone are most of your records in?")
    for index, zone in enumerate(zones, 1):
        say(f"  {index}) {zone['name']}")
    say(f"  {len(zones) + 1}) none - I'll set a zone per record")

    while True:
        choice = ask(f"Choice [1-{len(zones) + 1}]: ", "1")
        if choice.isdigit() and 1 <= int(choice) <= len(zones):
            return str(zones[int(choice) - 1]["name"])
        if choice.isdigit() and int(choice) == len(zones) + 1:
            return ""
        say("  pick one of the listed numbers")


def prompt_frequency() -> int:
    say()
    say("How often should it check whether your IP changed?")
    for index, (label, _) in enumerate(FREQUENCIES, 1):
        say(f"  {index}) {label}")

    while True:
        choice = ask(f"Choice [1-{len(FREQUENCIES)}] (default 2): ", "2")
        if not (choice.isdigit() and 1 <= int(choice) <= len(FREQUENCIES)):
            say("  pick one of the listed numbers")
            continue

        minutes = FREQUENCIES[int(choice) - 1][1]
        if minutes is not None:
            return minutes

        custom = ask("Minutes between runs: ")
        if not custom.isdigit() or not 1 <= int(custom) <= 1440:
            say("  enter a whole number of minutes between 1 and 1440")
            continue
        try:
            schedule.cron_schedule(int(custom))  # validate before committing
        except schedule.ScheduleError as err:
            say(f"  {err}")
            continue
        return int(custom)


def find_logs() -> list[Path]:
    """Log files to offer to delete, including one logPath points outside the project."""
    logs = set(ROOT.glob("*.log"))

    if CONFIG.exists():
        parser = ConfigParser()
        try:
            parser.read(CONFIG, encoding="utf-8")
            raw = parser.get("general", "logPath", fallback="").strip()
        except Exception:  # a hand-mangled ini shouldn't block uninstall
            raw = ""
        if raw:
            configured = Path(raw).expanduser()
            if not configured.is_absolute():
                configured = CONFIG.parent / configured
            if configured.is_file():
                logs.add(configured)

    return sorted(logs)


# --- commands ---------------------------------------------------------------

def do_install() -> int:
    if not sys.stdin.isatty():
        raise SystemExit(
            "Setup is interactive and needs a terminal. Run setup.sh / setup.ps1 directly."
        )

    say("Cloudflare DNS Sync - setup")
    say("=" * 46)

    if CONFIG.exists():
        say(f"{CONFIG.name} already exists; its token and zone will be updated in place.")
        say()

    token, api = prompt_token()
    try:
        site_name = prompt_zone(api)
    finally:
        api.close()

    write_config(token, site_name)
    minutes = prompt_frequency()

    if minutes:
        try:
            what = schedule.install(Path(sys.executable), ROOT / "main.py", minutes)
            say(f"  scheduled: {what}")
        except schedule.ScheduleError as err:
            say(f"  could not schedule it: {err}")
            say("  you can still run it by hand, or schedule it yourself.")
    else:
        say("  no schedule created")

    say()
    say("=" * 46)
    say("Almost there. Add the records you want synced:")
    say()
    say(f"  {CONFIG}")
    say()
    say("Each record gets its own section, for example:")
    say()
    say("  [DNS:home.example.com]")
    say()
    say("  [DNS:vpn.example.com]")
    say("  proxied = True")
    say()
    say("Then try it:")
    say(f"  {sys.executable} {ROOT / 'main.py'} -v")
    return 0


def do_uninstall(purge: bool) -> int:
    say("Cloudflare DNS Sync - uninstall")
    say("=" * 46)

    try:
        removed = schedule.uninstall()
        say("  removed the scheduled job" if removed else "  no scheduled job was installed")
    except schedule.ScheduleError as err:
        say(f"  could not remove the scheduled job: {err}")

    logs = find_logs()  # resolved before config.ini can be deleted

    if CONFIG.exists():
        if purge or confirm(f"  delete {CONFIG.name}? It holds your API token."):
            CONFIG.unlink()
            say(f"  deleted {CONFIG.name}")
        else:
            say(f"  kept {CONFIG.name}")

    if logs and (purge or confirm(f"  delete {len(logs)} log file(s)?")):
        for log in logs:
            log.unlink(missing_ok=True)
        say("  deleted log files")

    say()
    say("Done. Revoke the token if you're finished with it:")
    say("  https://dash.cloudflare.com/profile/api-tokens")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py", description="Set up (or tear down) Cloudflare DNS Sync."
    )
    parser.add_argument(
        "--uninstall", action="store_true", help="remove the scheduled job and config"
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help="with --uninstall, delete config.ini and logs without asking",
    )
    args = parser.parse_args(argv)

    try:
        return do_uninstall(args.purge) if args.uninstall else do_install()
    except KeyboardInterrupt:
        say()
        say("cancelled")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
