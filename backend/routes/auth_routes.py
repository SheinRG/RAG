"""
Nexus — Auth Routes
Wraps Supabase Auth for signup, login, and user info.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from supabase_auth.errors import AuthApiError

from database import supabase
from auth_middleware import get_current_user
from models.schemas import AuthRequest, AuthResponse, UserResponse, MessageResponse
from rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Authentication"])


@router.post("/register", response_model=MessageResponse)
@limiter.limit("10/minute")
async def register(request: Request, body: AuthRequest):
    """Register a new user via Supabase Auth."""
    # Always return the same neutral message so this endpoint can't be used to
    # enumerate which emails already have an account.
    neutral = MessageResponse(
        message="If that email is available, we've sent a confirmation link. Please check your inbox."
    )
    try:
        supabase.auth.sign_up({
            "email": body.email,
            "password": body.password,
        })
        return neutral

    except AuthApiError as e:
        # Log the real reason; don't reveal it (avoids enumeration / detail leak).
        logger.warning(f"Registration AuthApiError: {e}")
        return neutral
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again.",
        )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: AuthRequest):
    """Log in an existing user and return an access token."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })

        return AuthResponse(
            access_token=response.session.access_token,
            user={
                "id": str(response.user.id),
                "email": response.user.email,
            },
        )

    except AuthApiError as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed. Please try again.",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(user=Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
    )
