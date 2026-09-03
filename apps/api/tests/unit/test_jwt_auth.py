import time
import uuid

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.modules.auth.jwks as jwks_module
from app.modules.auth.dependencies import get_current_user
from tests._jwt_helpers import generate_es256_keypair, sign_token

_KID = "test-kid"
_PRIVATE_PEM, _JWK = generate_es256_keypair(_KID)


def _make_token(payload: dict, kid: str | None = _KID) -> str:
    return sign_token(payload, _PRIVATE_PEM, kid)


@pytest.fixture(autouse=True)
def _stub_jwks(monkeypatch):
    """Points auth.jwks at our local test key instead of a real network call,
    and resets the module-level cache so tests don't leak state into each other."""
    monkeypatch.setitem(jwks_module._cache, "keys_by_kid", {_KID: _JWK})
    monkeypatch.setitem(jwks_module._cache, "fetched_at", time.monotonic())

    async def _fake_fetch():
        return {_KID: _JWK}

    monkeypatch.setattr(jwks_module, "_fetch_jwks", _fake_fetch)
    yield


@pytest.mark.asyncio
async def test_valid_token_returns_authenticated_user():
    user_id = str(uuid.uuid4())
    token = _make_token({"sub": user_id, "email": "sdr@example.com", "aud": "authenticated"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    result = await get_current_user(credentials)

    assert str(result.auth_user_id) == user_id
    assert result.email == "sdr@example.com"


@pytest.mark.asyncio
async def test_missing_credentials_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_token_is_rejected():
    token = _make_token({"sub": str(uuid.uuid4()), "email": "a@b.com", "aud": "authenticated"})
    # Flip a character in the middle of the signature, not the last one: base64url's
    # final character can carry unused padding bits, so changing only it sometimes
    # decodes to the exact same signature bytes — a flaky no-op tamper.
    header, payload, signature = token.split(".")
    mid = len(signature) // 2
    flipped_char = "A" if signature[mid] != "A" else "B"
    tampered_signature = signature[:mid] + flipped_char + signature[mid + 1 :]
    tampered = f"{header}.{payload}.{tampered_signature}"
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tampered)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_token_missing_claims_is_rejected():
    token = _make_token({"aud": "authenticated"})  # no sub/email
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_is_rejected():
    token = _make_token(
        {"sub": str(uuid.uuid4()), "email": "a@b.com", "aud": "wrong-audience"}
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_kid_is_rejected():
    """A token signed with a key that isn't in this project's JWKS — e.g. from a
    different Supabase project — must not be accepted."""
    token = _make_token(
        {"sub": str(uuid.uuid4()), "email": "a@b.com", "aud": "authenticated"},
        kid="some-other-projects-key",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_kid_header_is_rejected():
    token = _make_token(
        {"sub": str(uuid.uuid4()), "email": "a@b.com", "aud": "authenticated"}, kid=None
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials)
    assert exc_info.value.status_code == 401
