"""Baseline security response headers.

Applied to every response (API, /docs, and the /uploads static mount). The most
important one for the app is `X-Content-Type-Options: nosniff`, which — together
with the upload extension whitelist + magic-byte check — stops an uploaded file
from ever being interpreted as active content.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # HSTS only makes sense over HTTPS; cookie_secure is our "production" signal.
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        # Uploaded files are never meant to be viewed as top-level documents.
        if request.url.path.startswith("/uploads"):
            h["Content-Disposition"] = "attachment"
        return response
