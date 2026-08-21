# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/Python-Cloudflare-DNS-External-IP-Synchronizer
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""Discovers this machine's public IP by asking a few echo services."""

from __future__ import annotations

import ipaddress
import logging
import random
import re

import requests

log = logging.getLogger(__name__)

SOURCES = {
    4: (
        "https://api.ipify.org",
        "https://ipv4.icanhazip.com",
        "https://checkip.amazonaws.com",
    ),
    6: (
        "https://api6.ipify.org",
        "https://ipv6.icanhazip.com",
    ),
}

_PATTERNS = {
    4: re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    6: re.compile(r"\b[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}\b"),
}


class NetworkError(Exception):
    """Every echo service failed, so the public IP is unknown."""


def extract(text: str, family: int) -> str | None:
    """Pull the first routable IP of the requested family out of a response body."""
    for match in _PATTERNS[family].findall(text):
        try:
            address = ipaddress.ip_address(match)
        except ValueError:
            continue
        if address.version == family and address.is_global:
            return str(address)
    return None


def get(family: int = 4, *, session: requests.Session | None = None, timeout: float = 5.0) -> str:
    """Return the public IPv4 (family=4) or IPv6 (family=6) address.

    Sources are tried in random order so no single service carries the load.
    """
    if family not in SOURCES:
        raise ValueError(f"unsupported address family: {family}")

    sources = list(SOURCES[family])
    random.shuffle(sources)
    http = session or requests

    for url in sources:
        try:
            response = http.get(url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as err:
            log.warning("IPv%d lookup failed at %s: %s", family, url, err)
            continue

        address = extract(response.text, family)
        if address:
            log.debug("public IPv%d is %s (via %s)", family, address, url)
            return address
        log.warning("IPv%d lookup returned no usable address at %s", family, url)

    raise NetworkError(f"could not determine public IPv{family} from any source")
