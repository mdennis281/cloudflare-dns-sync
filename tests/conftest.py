import pytest

from cfdns import config as config_module


@pytest.fixture(autouse=True)
def isolate_token_sources(monkeypatch, tmp_path):
    """Keep the developer's real token out of the tests.

    Without this, an exported CLOUDFLARE_API_TOKEN or a .env in the project
    root would satisfy configs the tests expect to fail.
    """
    monkeypatch.delenv(config_module.TOKEN_ENV_VAR, raising=False)
    monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path / "no-such-project-root")
