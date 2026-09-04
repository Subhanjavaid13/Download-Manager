import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import auth as auth_mod
from app.auth import AuthError, decode_token, user_from_claims
from app.config import Settings

SECRET = "unit-test-secret"


def _claims(**over) -> dict:
    base = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "email": "a@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "user_metadata": {"email_verified": True},
        "exp": int(time.time()) + 600,
    }
    base.update(over)
    return base


def test_hs256_token_decodes_with_secret() -> None:
    settings = Settings(supabase_jwt_secret=SECRET, _env_file=None)
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    user = user_from_claims(decode_token(token, settings))
    assert user.id == "11111111-1111-1111-1111-111111111111"
    assert user.email_verified is True


def test_hs256_without_secret_is_rejected() -> None:
    settings = Settings(supabase_url="https://x.supabase.co", _env_file=None)
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_token(token, settings)


def test_wrong_audience_and_expiry_are_rejected() -> None:
    settings = Settings(supabase_jwt_secret=SECRET, _env_file=None)
    with pytest.raises(AuthError):
        decode_token(jwt.encode(_claims(aud="anon"), SECRET, algorithm="HS256"), settings)
    with pytest.raises(AuthError):
        decode_token(
            jwt.encode(_claims(exp=int(time.time()) - 5), SECRET, algorithm="HS256"), settings
        )


def test_es256_token_decodes_via_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key()

    class FakeKey:
        key = public

    class FakeJwks:
        def get_signing_key_from_jwt(self, token: str) -> FakeKey:
            return FakeKey()

    monkeypatch.setattr(auth_mod, "_jwks_client", lambda url: FakeJwks())
    settings = Settings(supabase_url="https://x.supabase.co", _env_file=None)
    token = jwt.encode(_claims(), private, algorithm="ES256", headers={"kid": "k1"})
    user = user_from_claims(decode_token(token, settings))
    assert user.email == "a@example.com"


def test_unverified_flag() -> None:
    user = user_from_claims(_claims(user_metadata={"email_verified": False}))
    assert user.email_verified is False
    user = user_from_claims(_claims(user_metadata={}))
    assert user.email_verified is False


def test_garbage_token() -> None:
    settings = Settings(supabase_jwt_secret=SECRET, _env_file=None)
    with pytest.raises(AuthError):
        decode_token("not-a-token", settings)
