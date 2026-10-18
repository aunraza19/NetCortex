"""One Settings class for every environment variable.

Field names are the lowercase env var names (DATABASE_URL -> database_url). Secrets are
SecretStr, so they never show up in logs, reprs or tracebacks; call .get_secret_value()
at the point of use. NEXT_PUBLIC_* variables are read by apps/web only.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    # Shared database (Tiger Cloud: TimescaleDB + pgvector)
    database_url: SecretStr | None = None

    # Models (Ollama on the Mac, OpenAI-compatible API at <base>/v1)
    ollama_base_url: str = "http://localhost:11434"
    agent_model: str = "gemma4:e4b"
    embed_model: str = "embeddinggemma"  # must be identical on both sides, or search breaks

    # Detector
    tabpfn_mode: Literal["cloud", "local"] = "cloud"
    tabpfn_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("TABPFN_TOKEN", "TABPFN_API_KEY")
    )

    # Optional cloud add-ons; missing keys make them unavailable, never blocking
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str | None = None
    serpapi_api_key: SecretStr | None = None
    sentry_dsn_backend: str | None = None

    # Runtime
    temporal_address: str = "localhost:7233"
    demo_mode: bool = False
    http_timeout_s: float = Field(default=10.0, gt=0)  # default for every outbound call

    # Routers. Fixes go to CHR unless APPLY_TARGET=real is set explicitly.
    apply_target: Literal["chr", "real"] = "chr"
    chr_rest_url: str | None = None
    chr_username: str = "admin"
    chr_password: SecretStr = SecretStr("")

    # Live collector
    site_id_live: str = "home-lab"


@lru_cache
def get_settings() -> Settings:
    return Settings()
