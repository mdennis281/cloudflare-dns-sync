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

    def list_records(self, zone_id, type=""):
        return [
            dict(record, name=name, type=rtype)
            for (name, rtype), record in self.existing.items()
            if not type or rtype == type
        ]

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


def test_wildcard_updates_every_matching_record():
    api = FakeCloudflare({
        ("a.test.example.com", "A"): {"id": "r1", "content": "198.51.100.1"},
        ("b.test.example.com", "A"): {"id": "r2", "content": "198.51.100.2"},
        ("deep.b.test.example.com", "A"): {"id": "r3", "content": "198.51.100.3"},
        ("other.example.com", "A"): {"id": "r4", "content": "198.51.100.4"},
    })
    cfg = make_config(Record(name="*.test.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert sorted(p["name"] for _, p in api.updated) == [
        "a.test.example.com", "b.test.example.com", "deep.b.test.example.com",
    ]
    assert api.created == []


def test_wildcard_matches_case_insensitively_and_skips_current_records():
    api = FakeCloudflare({
        ("A.Test.Example.com", "A"): {"id": "r1", "content": "198.51.100.1"},
        ("b.test.example.com", "A"): {"id": "r2", "content": IP},
    })
    cfg = make_config(Record(name="*.TEST.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert [p["name"] for _, p in api.updated] == ["A.Test.Example.com"]


def test_wildcard_ignores_other_record_types():
    api = FakeCloudflare({
        ("a.test.example.com", "AAAA"): {"id": "r1", "content": "2606:4700::1"},
        ("b.test.example.com", "A"): {"id": "r2", "content": "198.51.100.2"},
    })
    cfg = make_config(Record(name="*.test.example.com"))

    sync(cfg, api, fake_lookup)
    assert [p["name"] for _, p in api.updated] == ["b.test.example.com"]


def test_wildcard_keeps_each_records_own_proxy_and_ttl():
    api = FakeCloudflare({
        ("a.test.example.com", "A"): {"id": "r1", "content": "198.51.100.1", "proxied": True, "ttl": 1},
        ("b.test.example.com", "A"): {"id": "r2", "content": "198.51.100.2", "proxied": False, "ttl": 300},
    })
    cfg = make_config(Record(name="*.test.example.com", proxied=False, ttl=120))

    sync(cfg, api, fake_lookup)
    by_name = {p["name"]: p for _, p in api.updated}
    assert by_name["a.test.example.com"]["proxied"] is True
    assert by_name["b.test.example.com"]["ttl"] == 300


def test_wildcard_creates_the_real_wildcard_record_when_nothing_matches():
    api = FakeCloudflare()
    cfg = make_config(Record(name="*.lanscape.app", zone="lanscape.app"))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.created == [
        {"type": "A", "name": "*.lanscape.app", "content": IP, "proxied": False, "ttl": 1}
    ]


def test_wildcard_updates_an_existing_wildcard_record_instead_of_duplicating_it():
    api = FakeCloudflare({("*.lanscape.app", "A"): {"id": "w1", "content": "198.51.100.9"}})
    cfg = make_config(Record(name="*.lanscape.app", zone="lanscape.app"))

    sync(cfg, api, fake_lookup)
    assert api.created == []
    assert api.updated[0][0] == "w1"


def test_wildcard_creates_nothing_when_create_record_is_off():
    api = FakeCloudflare()
    cfg = make_config(Record(name="*.lanscape.app", zone="lanscape.app", create=False))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.created == []


def test_mid_label_pattern_matches_but_is_never_created():
    api = FakeCloudflare()
    cfg = make_config(Record(name="dev-*.example.com"))

    assert sync(cfg, api, fake_lookup) == 0
    assert api.created == []
