"""
Nexus — Rate Limiting
Shared slowapi limiter. Keyed by client IP (honouring X-Forwarded-For behind a
proxy such as Render/nginx). In-memory storage — fine for a single instance.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _client_key(request: Request) -> str:
    """Prefer the real client IP from X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Global default protects every route; stricter per-route limits are applied
# with @limiter.limit(...) on auth and expensive LLM endpoints.
limiter = Limiter(key_func=_client_key, default_limits=["120/minute"])
