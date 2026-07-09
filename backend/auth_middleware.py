"""
Nexus — Authentication Middleware
JWT verification via Supabase Auth.
"""

import logging
from types import SimpleNamespace

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import supabase
from config import SUPABASE_JWT_SECRET

logger = logging.getLogger(__name__)
security = HTTPBearer()


def _verify_local(token: str):
    """
    Verify a Supabase access token locally (HS256) without a network call.
    Returns a lightweight user object (.id, .email) on success, or None if the
    shared secret is unset or the token is invalid/expired (caller then falls back).
    """
    if not SUPABASE_JWT_SECRET:
        return None
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as e:
        logger.debug(f"Local JWT verification failed, falling back to Supabase: {e}")
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None
    return SimpleNamespace(id=user_id, email=payload.get("email"))


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    FastAPI dependency that validates the Bearer token.
    Fast path: local JWT signature/expiry check (no round-trip). Falls back to an
    authoritative Supabase Auth lookup when the secret is unset or local verify fails.
    """
    token = credentials.credentials

    local_user = _verify_local(token)
    if local_user is not None:
        return local_user

    try:
        response = supabase.auth.get_user(token)
        user = response.user

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
            )

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
        )
