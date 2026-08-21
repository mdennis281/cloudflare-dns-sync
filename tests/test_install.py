from install import remove_ini_keys, set_env_value, set_ini_values

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


# --- .env editing -----------------------------------------------------------

def test_sets_the_token_in_an_env_file():
    body = "# comment\nCLOUDFLARE_API_TOKEN=your-api-token-here\n"
    result = set_env_value(body, "CLOUDFLARE_API_TOKEN", "real-token")
    assert result == "# comment\nCLOUDFLARE_API_TOKEN=real-token\n"


def test_keeps_other_variables_and_comments_in_the_env_file():
    body = "# keep me\nOTHER=1\nCLOUDFLARE_API_TOKEN=old\nAFTER=2\n"
    result = set_env_value(body, "CLOUDFLARE_API_TOKEN", "new")
    assert result.splitlines() == ["# keep me", "OTHER=1", "CLOUDFLARE_API_TOKEN=new", "AFTER=2"]


def test_appends_the_token_when_the_env_file_has_no_such_line():
    result = set_env_value("OTHER=1\n", "CLOUDFLARE_API_TOKEN", "new")
    assert result.splitlines() == ["OTHER=1", "CLOUDFLARE_API_TOKEN=new"]


def test_handles_an_empty_env_file():
    assert set_env_value("", "CLOUDFLARE_API_TOKEN", "new") == "CLOUDFLARE_API_TOKEN=new\n"


def test_replaces_an_exported_token_line():
    result = set_env_value("export CLOUDFLARE_API_TOKEN=old\n", "CLOUDFLARE_API_TOKEN", "new")
    assert result == "CLOUDFLARE_API_TOKEN=new\n"


def test_collapses_duplicate_token_lines():
    body = "CLOUDFLARE_API_TOKEN=one\nOTHER=x\nCLOUDFLARE_API_TOKEN=two\n"
    result = set_env_value(body, "CLOUDFLARE_API_TOKEN", "new")
    assert result.splitlines() == ["CLOUDFLARE_API_TOKEN=new", "OTHER=x"]


# --- removing the legacy token from config.ini ------------------------------

def test_removes_a_legacy_token_line_from_config_ini():
    text = "[CloudFlare-API]\ntoken = secret\nsiteName = example.com\n\n[DNS]\nproxied = False\n"
    result, removed = remove_ini_keys(text, "CloudFlare-API", {"token"})
    assert removed is True
    assert "secret" not in result
    assert "siteName = example.com" in result
    assert "[DNS]" in result


def test_reports_when_there_was_no_legacy_token_line():
    text = "[CloudFlare-API]\nsiteName = example.com\n"
    result, removed = remove_ini_keys(text, "CloudFlare-API", {"token"})
    assert removed is False
    assert result.strip() == text.strip()


def test_does_not_remove_a_token_key_from_another_section():
    text = "[CloudFlare-API]\ntoken = secret\n\n[other]\ntoken = keep-me\n"
    result, removed = remove_ini_keys(text, "CloudFlare-API", {"token"})
    assert removed is True
    assert "keep-me" in result
    assert "secret" not in result
