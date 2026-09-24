import pytest

from cfdns.config import ConfigError, Record, load, parse_size

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


# --- log rotation -----------------------------------------------------------

RECORD = "\n[DNS:a.example.com]\n\n[general]\n"


def test_rotation_defaults_to_five_one_megabyte_files(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS:a.example.com]\n"))
    assert (cfg.log_rotate, cfg.log_max_size, cfg.log_backups) == ("size", 1024 * 1024, 5)


def test_rotation_settings_are_read_from_the_general_section(tmp_path):
    cfg = load(write(tmp_path, RECORD + "logRotation = Daily\nlogMaxSize = 5 MB\nlogBackups = 30\n"))
    assert cfg.log_rotate == "daily"
    assert cfg.log_max_size == 5 * 1024 * 1024
    assert cfg.log_backups == 30


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1024", 1024),
        ("4096b", 4096),
        ("2KB", 2048),
        ("512 kib", 512 * 1024),
        ("5MB", 5 * 1024 ** 2),
        ("1.5mb", int(1.5 * 1024 ** 2)),
        ("1gb", 1024 ** 3),
    ],
)
def test_a_log_size_may_be_bytes_or_carry_a_suffix(text, expected):
    assert parse_size(text) == expected


def test_an_unknown_rotation_mode_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="logRotation must be one of"):
        load(write(tmp_path, RECORD + "logRotation = hourly\n"))


def test_a_log_size_that_is_not_a_size_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="is not a size"):
        load(write(tmp_path, RECORD + "logMaxSize = banana\n"))


def test_a_pointlessly_small_log_size_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="at least 1024 bytes"):
        load(write(tmp_path, RECORD + "logMaxSize = 100\n"))


def test_a_negative_backup_count_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="logBackups must be between"):
        load(write(tmp_path, RECORD + "logBackups = -1\n"))


def test_a_backup_count_that_is_not_a_number_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="invalid literal"):
        load(write(tmp_path, RECORD + "logBackups = lots\n"))



def test_wildcard_section_loads_as_a_pattern(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS:*.test.example.com]\nrecordType = A\n"))
    record = cfg.records[0]
    assert record.name == "*.test.example.com"
    assert record.is_pattern and record.is_creatable_wildcard


def test_a_mid_label_wildcard_is_a_pattern_but_not_creatable(tmp_path):
    cfg = load(write(tmp_path, "\n[DNS:dev-*.example.com]\n"))
    record = cfg.records[0]
    assert record.is_pattern and not record.is_creatable_wildcard


def test_a_wildcard_outside_its_zone_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="must end with its zone"):
        load(write(tmp_path, "\n[DNS:*.other.com]\n"))


def test_a_bare_wildcard_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="must end with its zone"):
        load(write(tmp_path, "\n[DNS:*]\n"))
