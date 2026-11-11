"""Request-level protections: CSRF defence and no-store caching for API responses.

CSRF policy for state-changing requests (any method except GET, HEAD, OPTIONS):

1. The request must carry the custom header `X-Requested-With: shift-copilot`. A page on another
   origin cannot add a custom header without a CORS preflight, and this app sends no CORS headers,
   so a cross-site form or fetch can never include it. This is the primary defence.
2. If a `Sec-Fetch-Site: cross-site` header is present, the request is refused.
3. If an `Origin` header is present, its host must equal the request's `Host` header (or an origin
   listed in ALLOWED_ORIGINS). `Origin: null` is refused. The scheme is
   not compared, because TLS ends at the proxy and the scheme the app sees is not trustworthy.
4. A request with NO Origin header is allowed only because it passed rule 1 (non-browser clients such as
   curl or the test client; browsers always send Origin on cross-origin state-changing requests).
The session cookie is also SameSite=Lax. Exempt: `/internal/digest`, which uses no cookie and is
authenticated by its X-Cron-Secret header.

Never add permissive CORS headers to this app without revisiting this file.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .config import settings
from .logging_setup import log_event

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "shift-copilot"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS = {"/internal/digest"}


def csrf_problem(method: str, path: str, headers: dict[str, str]) -> str | None:
    """Return the reason a request must be blocked, or None if it passes."""
    if method in SAFE_METHODS or path in EXEMPT_PATHS:
        return None
    if headers.get(CSRF_HEADER) != CSRF_VALUE:
        return "missing_header"
    if headers.get("sec-fetch-site") == "cross-site":
        return "cross_site"
    origin = headers.get("origin")
    if origin:
        if origin in _allowed_origins():
            return None
        host = urlsplit(origin).netloc if origin != "null" else ""
        if not host or host != headers.get("host", ""):
            return "origin_mismatch"
    return None


def _allowed_origins() -> set[str]:
    return {o.strip() for o in (settings.allowed_origins or "").split(",") if o.strip()}


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        path = scope.get("path", "")
        reason = csrf_problem(scope.get("method", "GET"), path, headers)
        if reason:
            log_event("csrf_blocked", "warning", reason=reason, method=scope.get("method"))
            body = json.dumps({"detail": "Request blocked."}).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and path.startswith("/api/"):
                message["headers"] = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"] + [
                    (b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, send_wrapper)
