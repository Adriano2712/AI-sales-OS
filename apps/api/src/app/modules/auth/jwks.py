import time
from typing import Any

import httpx

from app.core.config import get_settings

_CACHE_TTL_SECONDS = 24 * 60 * 60

# Module-level cache: Supabase's signing keys rotate rarely (not per-request),
# and fetching JWKS on every request would add a network round-trip to every
# authenticated call. Keyed by kid so get_signing_key can serve a rotated key
# immediately after one cache-miss-triggered refresh, without waiting for TTL.
_cache: dict[str, Any] = {"keys_by_kid": {}, "fetched_at": 0.0}


async def _fetch_jwks() -> dict[str, dict]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")
        response.raise_for_status()
    return {key["kid"]: key for key in response.json()["keys"]}


async def get_signing_key(kid: str) -> tuple[dict, str] | None:
    """Returns (jwk_dict, algorithm) for `kid`, or None if it's not a key this
    project's Supabase Auth actually issued.

    The algorithm comes from the JWK record itself (trusted — fetched by us
    over HTTPS from the project's own Supabase URL), never from the token's
    own header, which an attacker controls. This is what prevents classic
    JWT algorithm-confusion attacks: even a crafted token claiming `alg: HS256`
    in its header gets verified with whatever algorithm the matching *JWKS*
    entry says, using that entry's key material — a symmetric-key mismatch
    just fails to verify rather than being silently accepted.
    """
    now = time.monotonic()
    if not _cache["keys_by_kid"] or now - _cache["fetched_at"] > _CACHE_TTL_SECONDS:
        _cache["keys_by_kid"] = await _fetch_jwks()
        _cache["fetched_at"] = now

    jwk_dict = _cache["keys_by_kid"].get(kid)
    if jwk_dict is None:
        # Could be legitimate key rotation — refresh once before giving up.
        _cache["keys_by_kid"] = await _fetch_jwks()
        _cache["fetched_at"] = time.monotonic()
        jwk_dict = _cache["keys_by_kid"].get(kid)

    if jwk_dict is None:
        return None
    return jwk_dict, jwk_dict["alg"]
