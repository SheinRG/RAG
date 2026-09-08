"""Local JWT verification — the fast path that avoids a Supabase round-trip per request."""

import time

import jwt
import pytest
from fastapi import HTTPException

import auth_middleware

SECRET = "test-jwt-secret-at-least-32-bytes-long!!"


def make_token(secret=SECRET, *, sub="user-123", email="a@b.com", exp_offset=3600, aud="authenticated"):
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + exp_offset}
    if aud is not None:
        payload["aud"] = aud
    return jwt.encode(payload, secret, algorithm="HS256")


def test_valid_token_verifies_locally():
    user = auth_middleware._verify_local(make_token())
    assert user.id == "user-123"
    assert user.email == "a@b.com"


def test_expired_token_is_rejected():
    assert auth_middleware._verify_local(make_token(exp_offset=-60)) is None


def test_token_signed_with_another_secret_is_rejected():
    assert auth_middleware._verify_local(make_token(secret="attacker-secret")) is None


def test_token_with_wrong_audience_is_rejected():
    assert auth_middleware._verify_local(make_token(aud="anon")) is None


def test_token_without_subject_is_rejected():
    assert auth_middleware._verify_local(make_token(sub=None)) is None


def test_garbage_token_is_rejected():
    assert auth_middleware._verify_local("not-a-jwt") is None


def test_local_verification_is_skipped_when_no_shared_secret(monkeypatch):
    """Without the secret we must defer to Supabase, not accept blindly."""
    monkeypatch.setattr(auth_middleware, "SUPABASE_JWT_SECRET", "")
    assert auth_middleware._verify_local(make_token()) is None


@pytest.mark.asyncio
async def test_dependency_falls_back_to_supabase_when_local_verify_fails(monkeypatch):
    class Creds:
        credentials = "opaque-token"

    sentinel = object()

    class FakeAuth:
        def get_user(self, token):
            assert token == "opaque-token"
            return type("R", (), {"user": sentinel})()

    monkeypatch.setattr(auth_middleware, "supabase", type("S", (), {"auth": FakeAuth()})())
    assert await auth_middleware.get_current_user(Creds()) is sentinel


@pytest.mark.asyncio
async def test_dependency_401s_when_supabase_returns_no_user(monkeypatch):
    class Creds:
        credentials = "opaque-token"

    class FakeAuth:
        def get_user(self, token):
            return type("R", (), {"user": None})()

    monkeypatch.setattr(auth_middleware, "supabase", type("S", (), {"auth": FakeAuth()})())

    with pytest.raises(HTTPException) as exc:
        await auth_middleware.get_current_user(Creds())
    assert exc.value.status_code == 401
