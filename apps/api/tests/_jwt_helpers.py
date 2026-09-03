"""Shared test helper: generates a local EC keypair and signs ES256 tokens with
it, matching how real Supabase projects sign access tokens (observed: ES256
via JWKS — see app.modules.auth.jwks). Used by both unit and integration
tests so neither depends on network access to a real Supabase project's JWKS
endpoint or its email-confirmation settings.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt as jose_jwt


def _b64url_uint(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


def generate_es256_keypair(kid: str) -> tuple[bytes, dict]:
    """Returns (private_key_pem, public_jwk_dict)."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()
    jwk_dict = {
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "kid": kid,
        "use": "sig",
        "x": _b64url_uint(numbers.x),
        "y": _b64url_uint(numbers.y),
    }
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, jwk_dict


def sign_token(payload: dict, private_pem: bytes, kid: str | None) -> str:
    headers = {"kid": kid} if kid else None
    return jose_jwt.encode(payload, private_pem, algorithm="ES256", headers=headers)
