# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Loads config.ini into validated models.

A record is either the legacy ``[DNS]`` section or any ``[DNS:<name>]``
section. ``[DNS]`` doubles as the defaults for every ``[DNS:...]`` section.
"""

from __future__ import annotations

import os
import re
from configparser import ConfigParser
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from cfdns import logfile

CONFIG_ENV_VAR = "CF_DNS_CONFIG"
TOKEN_ENV_VAR = "CLOUDFLARE_API_TOKEN"
ENV_FILENAME = ".env"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SIZE_UNITS = {
    "": 1, "b": 1,
    "k": 1024, "kb": 1024, "kib": 1024,
    "m": 1024 ** 2, "mb": 1024 ** 2, "mib": 1024 ** 2,
    "g": 1024 ** 3, "gb": 1024 ** 3, "gib": 1024 ** 3,
}
MIN_LOG_SIZE = 1024  # a smaller ceiling than this rotates on every other line


class ConfigError(Exception):
    """config.ini is missing, unreadable, or incomplete."""


def parse_size(value: object) -> int:
    """Turn ``5MB``, ``512 kb`` or ``1048576`` into a byte count."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([a-z]*)", text)
    if not match or match.group(2) not in SIZE_UNITS:
        raise ValueError(
            f"{value!r} is not a size. Give bytes, or a suffix: 512KB, 5MB, 1GB."
        )
    return int(float(match.group(1)) * SIZE_UNITS[match.group(2)])


class Record(BaseModel):
    """One DNS record to keep pointed at the current public IP."""

    model_config = ConfigDict(frozen=True)

    name: str = ""  # blank only on the [DNS] defaults object
    type: str = "A"
    proxied: bool = False
    ttl: int = 1  # 1 means "automatic" to Cloudflare
    zone: str = ""  # empty falls back to Config.site_name
    create: bool = True

    @property
    def is_pattern(self) -> bool:
        """True for a wildcard name like ``*.lanscape.app`` or ``dev-*.example.com``."""
        return "*" in self.name

    @property
    def is_creatable_wildcard(self) -> bool:
        """True when Cloudflare would accept this pattern as a real record.

        Cloudflare only stores a wildcard as the leftmost label, so
        ``*.lanscape.app`` can be created but ``dev-*.lanscape.app`` can only
        ever match records that already exist.
        """
        return self.name.startswith("*.") and "*" not in self.name[2:]

    @field_validator("name", "zone", "type", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("type")
    @classmethod
    def _uppercase(cls, value: str) -> str:
        return value.upper()

    @field_validator("ttl")
    @classmethod
    def _ttl_in_range(cls, value: int) -> int:
        # 1 is Cloudflare's "automatic"; anything else must be a real TTL.
        if value != 1 and not 30 <= value <= 86400:
            raise ValueError("ttl must be 1 (automatic) or between 30 and 86400 seconds")
        return value


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str
    token_source: str = ""  # where the token came from, for messages
    site_name: str = ""
    records: tuple[Record, ...]
    source: Path
    log_enabled: bool = True
    log_level: int = 2
    log_path: str = "CF-DNS.log"
    log_rotate: str = logfile.SIZE
    log_max_size: int = logfile.DEFAULT_MAX_SIZE
    log_backups: int = logfile.DEFAULT_BACKUPS

    @field_validator("token", "site_name", "log_path", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("log_rotate", mode="before")
    @classmethod
    def _known_rotation(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        mode = value.strip().lower()
        if mode not in logfile.MODES:
            raise ValueError(
                f"logRotation must be one of {', '.join(logfile.MODES)}, not {value.strip()!r}"
            )
        return mode

    @field_validator("log_max_size", mode="before")
    @classmethod
    def _as_bytes(cls, value: object) -> object:
        return parse_size(value)

    @field_validator("log_max_size")
    @classmethod
    def _big_enough(cls, value: int) -> int:
        if value < MIN_LOG_SIZE:
            raise ValueError(f"logMaxSize must be at least {MIN_LOG_SIZE} bytes (1KB)")
        return value

    @field_validator("log_backups")
    @classmethod
    def _sane_backup_count(cls, value: int) -> int:
        if not 0 <= value <= 1000:
            raise ValueError("logBackups must be between 0 and 1000")
        return value

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if not self.token:
            raise ValueError(
                "no Cloudflare API token found. Put it in "
                f"{self.source.parent / ENV_FILENAME} as:\n"
                f"  {TOKEN_ENV_VAR}=your-token-here\n"
                f"(or export {TOKEN_ENV_VAR} in the environment)"
            )
        if not self.records:
            raise ValueError(
                f"no DNS records configured in {self.source}. "
                "Add a [DNS:your.host.example.com] section."
            )

        seen = set()
        for record in self.records:
            if not record.name:
                raise ValueError(f"a DNS section in {self.source} has no record name")
            if not self.zone_for(record):
                raise ValueError(
                    f'{record.name}: no zone. Set [CloudFlare-API] siteName, '
                    'or "zone" on the record.'
                )
            if record.is_pattern:
                zone = self.zone_for(record)
                lowered = record.name.lower()
                if not (lowered.endswith("." + zone.lower()) or lowered == zone.lower()):
                    raise ValueError(
                        f"{record.name}: a wildcard name must end with its zone "
                        f'("*.{zone}" or "*.sub.{zone}"), not match the whole account'
                    )
            key = (record.name, record.type)
            if key in seen:
                raise ValueError(f"{record.name} is configured twice as a {record.type} record")
            seen.add(key)
        return self

    def zone_for(self, record: Record) -> str:
        return record.zone or self.site_name

    def resolved_log_path(self) -> Path:
        """Relative log paths are resolved against the config file's directory."""
        path = Path(self.log_path).expanduser()
        return path if path.is_absolute() else self.source.parent / path


def find_env_file(config_path: Path) -> Path | None:
    """The .env beside config.ini, else the one in the project root."""
    for candidate in (config_path.parent / ENV_FILENAME, PROJECT_ROOT / ENV_FILENAME):
        if candidate.is_file():
            return candidate
    return None


def resolve_token(config_path: Path, from_ini: str = "") -> tuple[str, str]:
    """Find the API token and report where it came from.

    A real environment variable wins so systemd/CI can inject one; then the
    .env file; then config.ini, which is the deprecated pre-2.1 location.
    """
    from_environment = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if from_environment:
        return from_environment, f"${TOKEN_ENV_VAR}"

    env_file = find_env_file(config_path)
    if env_file is not None:
        token = (dotenv_values(env_file).get(TOKEN_ENV_VAR) or "").strip()
        if token:
            return token, str(env_file)

    if from_ini:
        return from_ini, "config.ini"

    return "", ""


def find_config(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Locate config.ini: explicit path, then $CF_DNS_CONFIG, project root, cwd."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"no config file at {path}")
        return path

    candidates = []
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        candidates.append(Path(from_env).expanduser())
    candidates += [PROJECT_ROOT / "config.ini", Path.cwd() / "config.ini"]

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = "\n  ".join(str(c) for c in candidates)
    raise ConfigError(f"could not find config.ini. Looked in:\n  {searched}")


def _read_record(parser: ConfigParser, section: str, name: str, defaults: Record) -> dict[str, object]:
    return {
        "name": parser.get(section, "name", fallback=name),
        "type": parser.get(section, "recordType", fallback=defaults.type),
        "proxied": parser.getboolean(section, "proxied", fallback=defaults.proxied),
        "ttl": parser.getint(section, "ttl", fallback=defaults.ttl),
        "zone": parser.get(section, "zone", fallback=defaults.zone),
        "create": parser.getboolean(section, "createRecord", fallback=defaults.create),
    }


def _first_error(err: ValidationError) -> str:
    """Pydantic wraps our messages in noise; surface the first one plainly."""
    first = err.errors()[0]
    message = str(first.get("msg", "")).removeprefix("Value error, ")
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{location}: {message}" if location and location not in message else message


def load(explicit: str | os.PathLike[str] | None = None) -> Config:
    path = find_config(explicit)
    parser = ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise ConfigError(f"could not read {path}")

    try:
        defaults = Record()
        if parser.has_section("DNS"):
            defaults = Record(**_read_record(parser, "DNS", "", defaults))

        records = []
        if defaults.name:  # pre-2.0 single-record layout
            records.append(defaults)
        for section in parser.sections():
            if section.startswith("DNS:"):
                name = section.split(":", 1)[1].strip()
                records.append(Record(**_read_record(parser, section, name, defaults)))

        token, token_source = resolve_token(
            path, parser.get("CloudFlare-API", "token", fallback="").strip()
        )
        return Config(
            token=token,
            token_source=token_source,
            site_name=parser.get("CloudFlare-API", "siteName", fallback=""),
            records=tuple(records),
            source=path,
            log_enabled=parser.getboolean("general", "loggingEnabled", fallback=True),
            log_level=parser.getint("general", "logLevel", fallback=2),
            log_path=parser.get("general", "logPath", fallback="CF-DNS.log"),
            log_rotate=parser.get("general", "logRotation", fallback=logfile.SIZE),
            log_max_size=parser.get("general", "logMaxSize", fallback=logfile.DEFAULT_MAX_SIZE),
            log_backups=parser.getint("general", "logBackups", fallback=logfile.DEFAULT_BACKUPS),
        )
    except ValidationError as err:
        raise ConfigError(_first_error(err)) from err
    except ValueError as err:  # configparser coercion, e.g. ttl = banana
        raise ConfigError(f"{path}: {err}") from err
