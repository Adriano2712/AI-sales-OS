import os

import pytest

# Settings() reads these at import time (app.core.config, app.core.db import chain).
# Unit tests never hit a real database, so any syntactically valid value is fine;
# integration tests override DATABASE_URL via TEST_DATABASE_URL (see
# tests/integration/conftest.py) before importing anything that touches the DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/postgres")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")


@pytest.fixture(autouse=True)
def _disable_apify_by_default(monkeypatch):
    """Settings() reads the real .env (Settings.model_config's env_file) and
    integration tests also `source .env` before running — so the real
    APIFY_API_TOKEN is a genuine env var in the test process, same as
    ANTHROPIC_API_KEY always has been. That was harmless for Anthropic
    because every business_analysis test explicitly substitutes
    AnthropicProvider regardless. discovery.py's build_providers() instead
    decides whether to include ApifyProvider *from the token alone* — a
    discovery test that never touches Apify at all would otherwise still
    construct a real ApifyProvider and make a real, paid network call
    (confirmed the hard way: this exact thing happened before this fixture
    existed). Forcing it off here, autouse, means "forgot to mock Apify" is
    structurally impossible to turn into "spent real money" (spec section
    39) — tests that actually want the multi-provider path opt back in
    explicitly (see test_discovery_job.py's _run_multi_provider_test)."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "apify_api_token", None)
