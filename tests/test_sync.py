from pathlib import Path

from cfdns.cloudflare import CloudflareError
from cfdns.config import Config, Record
from cfdns.sync import sync

IP = "203.0.113.7"


class FakeCloudflare:
    """Stand-in for the API: records calls, serves canned records."""

    def __init__(self, existing=None, fail_zone=None):
        self.existing = existing or {}
        self.fail_zone = fail_zone
        self.created = []
        self.updated = []

    def zone_id(self, zone):
        if zone == self.fail_zone:
            raise CloudflareError(f'zone "{zone}" does not exist on this account')
        return f"zid-{zone}"

    def find_record(self, zone_id, name, type):
        return self.existing.get((name, type))

    def create_record(self, zone_id, payload):
        self.created.append(payload)

    def update_record(self, zone_id, record_id, payload):
        self.updated.append((record_id, payload))


def make_config(*records, site_name="example.com"):
    return Config(
        token="tok",
        site_name=site_name,
        records=tuple(records),
        source=Path("config.ini"),
    )


def fake_lookup(family=4):
    return IP if family == 4 else "2606:4700:4700::1111"


def test_creates_a_missing_record():
    api = FakeCloudflare()
    cfg = make_config(Record(name="home.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.created == [
        {"type": "A", "name": "home.example.com", "content": IP, "proxied": False, "ttl": 1}
    ]


def test_does_not_create_when_create_record_is_off():
    api = FakeCloudflare()
    cfg = make_config(Record(name="home.example.com", create=False))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.created == []


def test_updates_a_stale_record():
    api = FakeCloudflare({("home.example.com", "A"): {"id": "r1", "content": "198.51.100.1"}})
    cfg = make_config(Record(name="home.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.updated[0][0] == "r1"
    assert api.updated[0][1]["content"] == IP


def test_leaves_an_up_to_date_record_alone():
    api = FakeCloudflare({("home.example.com", "A"): {"id": "r1", "content": IP}})
    cfg = make_config(Record(name="home.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.updated == [] and api.created == []


def test_proxied_records_are_forced_to_automatic_ttl():
    api = FakeCloudflare()
    cfg = make_config(Record(name="home.example.com", proxied=True, ttl=300))

    sync(cfg, api, fake_lookup)
    assert api.created[0]["ttl"] == 1


def test_aaaa_record_gets_the_ipv6_address():
    api = FakeCloudflare()
    cfg = make_config(Record(name="home.example.com", type="AAAA"))

    sync(cfg, api, fake_lookup)
    assert api.created[0]["content"] == "2606:4700:4700::1111"


def test_public_ip_is_looked_up_once_per_family():
    calls = []

    def counting_lookup(family=4):
        calls.append(family)
        return fake_lookup(family)

    api = FakeCloudflare()
    cfg = make_config(
        Record(name="a.example.com"),
        Record(name="b.example.com"),
        Record(name="c.example.com", type="AAAA"),
    )

    sync(cfg, api, counting_lookup)
    assert calls == [4, 6]


def test_one_failing_record_does_not_stop_the_others():
    api = FakeCloudflare(fail_zone="broken.com")
    cfg = make_config(
        Record(name="bad.broken.com", zone="broken.com"),
        Record(name="good.example.com"),
    )

    assert sync(cfg, api, fake_lookup) == 1
    assert [p["name"] for p in api.created] == ["good.example.com"]


def test_non_ip_record_type_is_reported_as_a_failure():
    api = FakeCloudflare()
    cfg = make_config(Record(name="home.example.com", type="CNAME"))

    assert sync(cfg, api, fake_lookup) == 1
    assert api.created == []
