# Author: Michael Dennis (https://github.com/mdennis281)
# Project Repository: https://github.com/mdennis281/cloudflare-dns-sync
# License: MIT (https://en.wikipedia.org/wiki/MIT_License)
"""A very small Cloudflare API v4 client: zone lookup and DNS record CRUD."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

API_URL = "https://api.cloudflare.com/client/v4"

log = logging.getLogger(__name__)


class CloudflareError(Exception):
    """The Cloudflare API rejected a call or could not be reached."""


class Cloudflare:
    """Reuses one HTTP session (and one TLS handshake) across every record."""

    def __init__(self, token: str, timeout: float = 10.0):
        self.timeout = timeout
        self._zone_ids: dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            # POST is deliberately absent: a retried create could duplicate a record.
            allowed_methods=("GET", "PUT"),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def __enter__(self) -> "Cloudflare":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.session.request(
                method, f"{API_URL}/{path}", timeout=self.timeout, **kwargs
            )
        except requests.RequestException as err:
            raise CloudflareError(f"could not reach the Cloudflare API: {err}") from err

        try:
            body = response.json()
        except ValueError as err:
            raise CloudflareError(
                f"Cloudflare returned a non-JSON response (HTTP {response.status_code})"
            ) from err

        if not body.get("success"):
            messages = "; ".join(
                str(e.get("message", e)) for e in body.get("errors") or []
            )
            raise CloudflareError(messages or f"HTTP {response.status_code} from {path}")
        return body.get("result")

    def verify_token(self) -> dict[str, Any]:
        """Check the API token is valid and active. Used by the installer."""
        return self._call("GET", "user/tokens/verify")

    def zones(self) -> list[dict[str, Any]]:
        """Every zone this token can see."""
        return self._call("GET", "zones", params={"per_page": 50}) or []

    def zone_id(self, zone: str) -> str:
        """Look up a zone's ID, caching it for the life of this client."""
        if zone not in self._zone_ids:
            zones = self._call("GET", "zones", params={"name": zone}) or []
            match = next((z for z in zones if z["name"] == zone), None)
            if match is None:
                raise CloudflareError(f'zone "{zone}" does not exist on this account')
            self._zone_ids[zone] = match["id"]
        return self._zone_ids[zone]

    def find_record(self, zone_id: str, name: str, type: str) -> dict[str, Any] | None:
        records = self._call(
            "GET", f"zones/{zone_id}/dns_records", params={"name": name, "type": type}
        ) or []
        return next(
            (r for r in records if r["name"] == name and r["type"] == type), None
        )

    def create_record(self, zone_id: str, payload: dict[str, Any]) -> None:
        self._call("POST", f"zones/{zone_id}/dns_records", json=payload)

    def update_record(self, zone_id: str, record_id: str, payload: dict[str, Any]) -> None:
        self._call("PUT", f"zones/{zone_id}/dns_records/{record_id}", json=payload)
