# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/Python-Cloudflare-DNS-External-IP-Synchronizer
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Points every configured DNS record at the current public IP."""

from __future__ import annotations

import logging
from typing import Callable

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
    existing = api.find_record(zone_id, record.name, record.type)
    payload = {
        "type": record.type,
        "name": record.name,
        "content": ip,
        "proxied": record.proxied,
        # Cloudflare requires ttl=1 ("automatic") on proxied records.
        "ttl": 1 if record.proxied else record.ttl,
    }

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
