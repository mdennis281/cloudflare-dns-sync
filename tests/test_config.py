import pytest

from cfdns.config import ConfigError, Record, load

BASE = """
[CloudFlare-API]
token = tok
siteName = example.com
"""


def write(tmp_path, body):
    path = tmp_path / "config.ini"
    path.write_text(BASE + body, encoding="utf-8")
    return path


def test_legacy_single_dns_section_still_works(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS]\nname = home.example.com\nrecordType = A\n"))
    assert cfg.records == (Record(name="home.example.com", type="A"),)
    assert cfg.zone_for(cfg.records[0]) == "example.com"


def test_multiple_records_inherit_dns_defaults(tmp_path):
    cfg = load(
        write(
            tmp_path,
            """
[DNS]
recordType = A
proxied = True
createRecord = False

[DNS:home.example.com]

[DNS:vpn.example.com]
proxied = False
recordType = AAAA
""",
        )
    )
    home, vpn = cfg.records
    assert [r.name for r in cfg.records] == ["home.example.com", "vpn.example.com"]
    assert home.proxied is True and home.create is False and home.type == "A"
    assert vpn.proxied is False and vpn.type == "AAAA"
    # A bare [DNS] defaults section is not itself a record.
    assert len(cfg.records) == 2


def test_per_record_zone_overrides_site_name(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS:nas.other.com]\nzone = other.com\n"))
    assert cfg.zone_for(cfg.records[0]) == "other.com"


def test_missing_token_is_an_error(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("[DNS:a.example.com]\nzone = example.com\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="token"):
        load(path)


def test_no_records_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="no DNS records"):
        load(write(tmp_path, ""))


def test_duplicate_record_is_an_error(tmp_path):
    body = "\n[DNS]\nname = home.example.com\n\n[DNS:home.example.com]\n"
    with pytest.raises(ConfigError, match="twice"):
        load(write(tmp_path, body))


def test_missing_config_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="no config file"):
        load(tmp_path / "nope.ini")


def test_relative_log_path_resolves_next_to_config(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS:a.example.com]\n\n[general]\nlogPath = logs/cf.log\n"))
    assert cfg.resolved_log_path() == tmp_path / "logs" / "cf.log"
