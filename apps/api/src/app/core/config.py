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

    gemini_api_key: str | None = None
    """Second AI provider (Fase 2 — Model Router). Optional, same
    degrade-gracefully pattern as anthropic_api_key: a task routed to Gemini
    without a key configured raises a clear error rather than silently
    falling back, since fallback must be an explicit per-task choice (spec:
    never fall back for a task incompatible with the other model)."""

    apify_api_token: str | None = None
    """Second discovery provider, alongside OSM/Overpass. Optional by
    design: discovery.py's job handler only adds ApifyProvider to its
    provider list when this is set, so the system degrades to OSM-only
    (not an error) if it's ever unset — same optional-until-configured
    pattern as anthropic_api_key."""
    apify_discovery_actor: str = "compass/crawler-google-places"
    """Actor id in `username/actor-name` form. Verified against the real
    Apify API before use — see docs/DISCOVERY.md."""

    gmail_smtp_user: str | None = None
    gmail_smtp_app_password: str | None = None
    daily_digest_recipient_email: str | None = None
    """Daily digest email (workers/scheduler.py). All three optional —
    unset means the scheduler logs and skips sending, same
    degrade-gracefully pattern as apify_api_token."""

    daily_discovery_tenant_id: str | None = None
    """Which tenant the daily scheduled campaign runs for. Unset means the
    scheduler does nothing — there's no sane default tenant to guess."""

    sender_company_name: str | None = None
    sender_company_location: str | None = None
    """Real identity of the software house sending outreach messages
    (messages/ai_writer.py). Both optional — unset means the AI Writer stays
    generic ("uma software house") rather than naming one. Added after a
    real finding: without this, the model would improvise a fabricated
    "daqui de [cidade do prospect]" line implying local presence that
    doesn't exist (spec section 35 — never invent, including implicitly)."""

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
