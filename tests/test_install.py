from install import set_ini_values

EXAMPLE = """# Copy this file to config.ini and fill it in.

[CloudFlare-API]
token = your-api-token-here
# Default zone for every record below.
siteName = mydomain.com

[DNS:home.mydomain.com]
recordType = A

[DNS]
proxied = False
"""


def test_replaces_values_in_the_right_section():
    result = set_ini_values(EXAMPLE, "CloudFlare-API", {"token": "abc123", "siteName": "real.com"})
    assert "token = abc123" in result
    assert "siteName = real.com" in result
    assert "your-api-token-here" not in result


def test_keeps_comments_and_every_other_section():
    result = set_ini_values(EXAMPLE, "CloudFlare-API", {"token": "abc123"})
    assert "# Copy this file to config.ini and fill it in." in result
    assert "# Default zone for every record below." in result
    assert "[DNS:home.mydomain.com]" in result
    assert "recordType = A" in result
    assert "[DNS]" in result


def test_does_not_touch_a_same_named_key_in_another_section():
    text = "[CloudFlare-API]\ntoken = old\n\n[other]\ntoken = leave-me\n"
    result = set_ini_values(text, "CloudFlare-API", {"token": "new"})
    assert "token = new" in result
    assert "token = leave-me" in result
    assert "token = old" not in result


def test_adds_a_missing_key_inside_the_existing_section():
    text = "[CloudFlare-API]\ntoken = old\n\n[DNS]\nproxied = False\n"
    result = set_ini_values(text, "CloudFlare-API", {"token": "new", "siteName": "real.com"})
    lines = result.splitlines()
    assert lines.index("siteName = real.com") < lines.index("[DNS]")


def test_adds_the_section_when_it_is_absent_entirely():
    result = set_ini_values("[DNS]\nproxied = False\n", "CloudFlare-API", {"token": "new"})
    assert "[CloudFlare-API]" in result
    assert "token = new" in result


def test_matches_keys_case_insensitively_like_configparser():
    text = "[CloudFlare-API]\nToken = old\nSITENAME = old.com\n"
    result = set_ini_values(text, "CloudFlare-API", {"token": "new", "siteName": "real.com"})
    assert "token = new" in result
    assert "siteName = real.com" in result
    assert "old" not in result


def test_result_is_still_parseable_by_configparser(tmp_path):
    from configparser import ConfigParser

    path = tmp_path / "config.ini"
    path.write_text(
        set_ini_values(EXAMPLE, "CloudFlare-API", {"token": "abc123"}), encoding="utf-8"
    )
    parser = ConfigParser()
    parser.read(path, encoding="utf-8")
    assert parser.get("CloudFlare-API", "token") == "abc123"
    assert parser.has_section("DNS:home.mydomain.com")
