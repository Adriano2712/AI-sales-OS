from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str
    """Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/postgres"""

    redis_url: str

    supabase_url: str
    """Also used to derive the JWKS endpoint for JWT verification — see
    app.modules.auth.jwks. Supabase's current default signs tokens with an
    asymmetric key (observed: ES256), not the legacy HS256 shared secret, so
    there is no separate JWT-secret setting here."""

    anthropic_api_key: str | None = None

    apify_api_token: str | None = None
    """Second discovery provider, alongside OSM/Overpass. Optional by
    design: discovery.py's job handler only adds ApifyProvider to its
    provider list when this is set, so the system degrades to OSM-only
    (not an error) if it's ever unset — same optional-until-configured
    pattern as anthropic_api_key."""
    apify_discovery_actor: str = "compass/crawler-google-places"
    """Actor id in `username/actor-name` form. Verified against the real
    Apify API before use — see docs/DISCOVERY.md."""

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
