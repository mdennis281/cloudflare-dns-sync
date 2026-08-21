import pytest

from cfdns import config as config_module
from cfdns.config import TOKEN_ENV_VAR, ConfigError, load, resolve_token

CONFIG_BODY = """
[CloudFlare-API]
siteName = example.com

[DNS:home.example.com]
"""


def write_config(tmp_path, body=CONFIG_BODY):
    path = tmp_path / "config.ini"
    path.write_text(body, encoding="utf-8")
    return path


def write_env(tmp_path, contents):
    path = tmp_path / ".env"
    path.write_text(contents, encoding="utf-8")
    return path


def test_token_is_read_from_the_env_file(tmp_path):
    write_env(tmp_path, f"{TOKEN_ENV_VAR}=from-env-file\n")
    cfg = load(write_config(tmp_path))
    assert cfg.token == "from-env-file"
    assert cfg.token_source == str(tmp_path / ".env")


def test_env_file_comments_and_other_vars_are_ignored(tmp_path):
    write_env(
        tmp_path,
        f"# a comment\nOTHER_THING=nope\n\n{TOKEN_ENV_VAR}=the-real-token\n",
    )
    assert load(write_config(tmp_path)).token == "the-real-token"


def test_exported_environment_variable_beats_the_env_file(tmp_path, monkeypatch):
    write_env(tmp_path, f"{TOKEN_ENV_VAR}=from-env-file\n")
    monkeypatch.setenv(TOKEN_ENV_VAR, "from-environment")

    cfg = load(write_config(tmp_path))
    assert cfg.token == "from-environment"
    assert cfg.token_source == f"${TOKEN_ENV_VAR}"


def test_env_file_beats_a_legacy_token_in_config_ini(tmp_path):
    write_env(tmp_path, f"{TOKEN_ENV_VAR}=from-env-file\n")
    path = write_config(
        tmp_path, "\n[CloudFlare-API]\ntoken = from-ini\nsiteName = example.com\n\n[DNS:a.example.com]\n"
    )
    assert load(path).token == "from-env-file"


def test_legacy_token_in_config_ini_still_works(tmp_path):
    path = write_config(
        tmp_path, "\n[CloudFlare-API]\ntoken = from-ini\nsiteName = example.com\n\n[DNS:a.example.com]\n"
    )
    cfg = load(path)
    assert cfg.token == "from-ini"
    # cli.py keys the "move your token" warning off this exact value.
    assert cfg.token_source == "config.ini"


def test_env_file_next_to_config_wins_over_the_project_root_one(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env").write_text(f"{TOKEN_ENV_VAR}=root-token\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "PROJECT_ROOT", project_root)

    beside = tmp_path / "beside"
    beside.mkdir()
    write_env(beside, f"{TOKEN_ENV_VAR}=beside-token\n")

    assert load(write_config(beside)).token == "beside-token"


def test_project_root_env_is_used_when_config_lives_elsewhere(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env").write_text(f"{TOKEN_ENV_VAR}=root-token\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "PROJECT_ROOT", project_root)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert load(write_config(elsewhere)).token == "root-token"


def test_no_token_anywhere_points_the_user_at_the_env_file(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load(write_config(tmp_path))

    message = str(excinfo.value)
    assert "no Cloudflare API token found" in message
    assert str(tmp_path / ".env") in message
    assert TOKEN_ENV_VAR in message


def test_blank_token_in_env_file_is_not_a_token(tmp_path):
    write_env(tmp_path, f"{TOKEN_ENV_VAR}=   \n")
    with pytest.raises(ConfigError, match="no Cloudflare API token found"):
        load(write_config(tmp_path))


def test_resolve_token_reports_nothing_when_there_is_nothing(tmp_path):
    assert resolve_token(tmp_path / "config.ini") == ("", "")
