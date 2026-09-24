# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Points every configured DNS record at the current public IP."""

from __future__ import annotations

import fnmatch
import logging
from typing import Any, Callable

from cfdns.cloudflare import Cloudflare, CloudflareError
from cfdns.config import Config, ConfigError, Record
from cfdns.public_ip import NetworkError
from cfdns import public_ip

# Record types this tool knows how to fill in, and the IP family each needs.
FAMILIES = {"A": 4, "AAAA": 6}

log = logging.getLogger(__name__)


def sync(cfg: Config, api: Cloudflare, ip_lookup: Callable[..., str] = public_ip.get) -> int:
    """Sync every record, returning the number that failed.

    One bad record does not stop the rest: each failure is logged and the
    loop moves on, so a typo in one hostname cannot strand the others.
    """
    ip_cache: dict[int, str] = {}
    failures = 0

    for record in cfg.records:
        try:
            _sync_record(cfg, api, record, ip_cache, ip_lookup)
        except (CloudflareError, NetworkError, ConfigError) as err:
            log.error("%s: %s", record.name, err)
            failures += 1

    return failures


def _sync_record(
    cfg: Config,
    api: Cloudflare,
    record: Record,
    ip_cache: dict[int, str],
    ip_lookup: Callable[..., str],
) -> None:
    family = FAMILIES.get(record.type)
    if family is None:
        raise ConfigError(
            f'recordType "{record.type}" holds no IP address; only {"/".join(FAMILIES)} can be synced'
        )

    if family not in ip_cache:
        ip_cache[family] = ip_lookup(family)
    ip = ip_cache[family]

    zone_id = api.zone_id(cfg.zone_for(record))

    if record.is_pattern:
        _sync_pattern(api, record, zone_id, ip)
        return

    existing = api.find_record(zone_id, record.name, record.type)
    payload = _payload(record, record.name, ip)

    if existing is None:
        if not record.create:
            log.info("%s: no such record. Set createRecord = True to have it created.", record.name)
            return
        api.create_record(zone_id, payload)
        log.info("%s: created %s record pointing at %s", record.name, record.type, ip)
    elif existing.get("content") != ip:
        api.update_record(zone_id, existing["id"], payload)
        log.info(
            "%s: updated %s record to %s (was %s)",
            record.name, record.type, ip, existing.get("content"),
        )
    else:
        log.debug("%s: already points at %s", record.name, ip)


def _payload(record: Record, name: str, ip: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the PUT/POST body.

    A wildcard section describes many records that were set up individually,
    so their own proxy and TTL settings win -- only the IP is ours to change.
    ``existing`` is passed for exactly that case.
    """
    proxied = record.proxied if existing is None else bool(existing.get("proxied", False))
    ttl = record.ttl if existing is None else int(existing.get("ttl", 1) or 1)
    return {
        "type": record.type,
        "name": name,
        "content": ip,
        "proxied": proxied,
        # Cloudflare requires ttl=1 ("automatic") on proxied records.
        "ttl": 1 if proxied else ttl,
    }


def matches(pattern: str, name: str) -> bool:
    """Glob-match a DNS name, case-insensitively.

    ``*`` spans any number of labels, so ``*.test.example.com`` covers
    ``a.test.example.com`` and ``a.b.test.example.com`` alike -- and the
    Cloudflare wildcard record ``*.test.example.com`` itself.
    """
    return fnmatch.fnmatchcase(name.lower(), pattern.lower())


def _sync_pattern(api: Cloudflare, record: Record, zone_id: str, ip: str) -> None:
    """Point every existing record matching the pattern at the current IP."""
    found = [
        existing
        for existing in api.list_records(zone_id, record.type)
        if matches(record.name, existing.get("name", ""))
    ]

    if not found:
        if not record.create:
            log.info("%s: matched no records. Set createRecord = True to have it created.", record.name)
        elif record.is_creatable_wildcard:
            api.create_record(zone_id, _payload(record, record.name, ip))
            log.info("%s: created wildcard %s record pointing at %s", record.name, record.type, ip)
        else:
            # Cloudflare stores a wildcard only as the leftmost label, so
            # there is nothing this pattern could be turned into.
            log.info(
                "%s: matched no records, and Cloudflare cannot create a record from "
                "this pattern (only *.name is a real wildcard).",
                record.name,
            )
        return

    changed = 0
    for existing in found:
        name = existing["name"]
        if existing.get("content") == ip:
            log.debug("%s: already points at %s (matched %s)", name, ip, record.name)
            continue
        api.update_record(zone_id, existing["id"], _payload(record, name, ip, existing))
        changed += 1
        log.info(
            "%s: updated %s record to %s (was %s, matched %s)",
            name, record.type, ip, existing.get("content"), record.name,
        )

    log.debug("%s: matched %d record(s), updated %d", record.name, len(found), changed)
