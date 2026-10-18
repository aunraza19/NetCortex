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
    serpapi_api_key: SecretStr | None = None
    sentry_dsn_backend: str | None = None

    # Runtime
    temporal_address: str = "localhost:7233"
    demo_mode: bool = False
    http_timeout_s: float = Field(default=10.0, gt=0)  # default for every outbound call

    # Routers. Fixes go to CHR unless APPLY_TARGET=real is set explicitly.
    apply_target: Literal["chr", "real"] = "chr"
    chr_rest_url: str | None = None
    chr_username: str | None = None
    chr_password: SecretStr | None = None

    # Live collector
    site_id_live: str = "home-lab"
    collector_interval_s: float = Field(default=10.0, gt=0)
    collector_pings: int = Field(default=5, ge=1)  # pings (and DNS lookups) per target per round
    collector_ping_timeout_s: float = Field(default=1.0, gt=0)
    collector_gateway: str | None = None  # default: hop 1 of a traceroute at startup
    collector_upstream_hop: str | None = None  # default: hop 2 of that traceroute
    collector_public_targets: list[str] = ["1.1.1.1", "8.8.8.8"]
    collector_game_server: str | None = None  # one regional game server to ping
    collector_dns_resolvers: list[str] = ["1.1.1.1", "8.8.8.8"]  # stored as dns:<resolver>
    collector_dns_query: str = "google.com"
    collector_dns_timeout_s: float = Field(default=2.0, gt=0)
    collector_router_stats: bool = False  # read interface/queue stats from CHR_REST_URL
    collector_router_interval_s: float = Field(default=30.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
