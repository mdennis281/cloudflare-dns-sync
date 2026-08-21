# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Loads config.ini into validated models.

A record is either the legacy ``[DNS]`` section or any ``[DNS:<name>]``
section. ``[DNS]`` doubles as the defaults for every ``[DNS:...]`` section.
"""

from __future__ import annotations

import os
from configparser import ConfigParser
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

CONFIG_ENV_VAR = "CF_DNS_CONFIG"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """config.ini is missing, unreadable, or incomplete."""


class Record(BaseModel):
    """One DNS record to keep pointed at the current public IP."""

    model_config = ConfigDict(frozen=True)

    name: str = ""  # blank only on the [DNS] defaults object
    type: str = "A"
    proxied: bool = False
    ttl: int = 1  # 1 means "automatic" to Cloudflare
    zone: str = ""  # empty falls back to Config.site_name
    create: bool = True

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
    site_name: str = ""
    records: tuple[Record, ...]
    source: Path
    log_enabled: bool = True
    log_level: int = 2
    log_path: str = "CF-DNS.log"

    @field_validator("token", "site_name", "log_path", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check(self) -> "Config":
        if not self.token:
            raise ValueError(f"[CloudFlare-API] token is not set in {self.source}")
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

        return Config(
            token=parser.get("CloudFlare-API", "token", fallback=""),
            site_name=parser.get("CloudFlare-API", "siteName", fallback=""),
            records=tuple(records),
            source=path,
            log_enabled=parser.getboolean("general", "loggingEnabled", fallback=True),
            log_level=parser.getint("general", "logLevel", fallback=2),
            log_path=parser.get("general", "logPath", fallback="CF-DNS.log"),
        )
    except ValidationError as err:
        raise ConfigError(_first_error(err)) from err
    except ValueError as err:  # configparser coercion, e.g. ttl = banana
        raise ConfigError(f"{path}: {err}") from err
