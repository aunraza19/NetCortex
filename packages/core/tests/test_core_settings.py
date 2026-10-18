import secrets

import pytest
from netcortex_core import Settings
from pydantic import ValidationError

ENV_VARS = [
    "DATABASE_URL",
    "OLLAMA_BASE_URL",
    "AGENT_MODEL",
    "EMBED_MODEL",
    "TABPFN_TOKEN",
    "TABPFN_API_KEY",
    "APPLY_TARGET",
    "SITE_ID_LIVE",
    "DEMO_MODE",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)  # never read the developer's .env in tests


def test_safe_defaults():
    settings = make()
    assert settings.apply_target == "chr"
    assert settings.site_id_live == "home-lab"
    assert settings.agent_model == "gemma4:e4b"
    assert settings.embed_model == "embeddinggemma"
    assert settings.database_url is None
    assert settings.demo_mode is False


def test_env_vars_map_to_lowercase_fields(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://mac-mini:11434")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("TABPFN_API_KEY", "tok")
    settings = make()
    assert settings.ollama_base_url == "http://mac-mini:11434"
    assert settings.demo_mode is True
    assert settings.tabpfn_token.get_secret_value() == "tok"


def test_apply_target_only_accepts_chr_or_real(monkeypatch):
    monkeypatch.setenv("APPLY_TARGET", "router")
    with pytest.raises(ValidationError):
        make()


def test_secrets_are_masked_when_printed(monkeypatch):
    password = secrets.token_hex(8)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://tester:{password}@db.invalid:5432/tsdb")
    settings = make()
    assert password not in repr(settings) and password not in str(settings)
    assert settings.database_url.get_secret_value().endswith("/tsdb")


def test_empty_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("AGENT_MODEL", "")
    settings = make()
    assert settings.database_url is None
    assert settings.agent_model == "gemma4:e4b"
