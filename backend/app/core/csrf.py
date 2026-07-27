"""CSRF protection via the double-submit-cookie pattern.

On login we set a readable `csrf` cookie in addition to the httpOnly session
cookie. State-changing requests from the SPA must echo that value in the
`X-CSRF-Token` header; this middleware rejects unsafe requests where the header
does not match the cookie.

Enforcement only applies when a session cookie is present — i.e. authenticated
requests carrying ambient authority. Public/unauthenticated calls (login,
signup, verify-email, forgot/reset-password, invite accept-signup) have no
session cookie to abuse and are therefore skipped.
"""

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import settings

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS:
            session = request.cookies.get(settings.session_cookie_name)
            if session:  # authenticated → require double-submit token
                cookie_token = request.cookies.get(settings.csrf_cookie_name)
                header_token = request.headers.get("X-CSRF-Token")
                if not (cookie_token and header_token and
                        secrets.compare_digest(cookie_token, header_token)):
                    return JSONResponse(
                        {"detail": "CSRF token missing or invalid"}, status_code=403
                    )
        return await call_next(request)
