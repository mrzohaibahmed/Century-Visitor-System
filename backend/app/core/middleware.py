"""
ASGI middleware:

- RequestContextMiddleware: assigns a request ID (reusing a well-formed incoming
  X-Request-ID), returns it in the response and writes one access-log line per
  request. The query string is NOT logged: it can contain identity numbers.
- SecurityHeadersMiddleware: safe defaults for every API response. No HSTS:
  production serves plain HTTP on the trusted LAN (CG_DEPLOYMENT_MODE=http-lan).
"""
import logging
import re
import time
import uuid

from app.core.request_context import reset_request_id, set_request_id

access_log = logging.getLogger("app.access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

API_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]
# The interactive docs page (development only) needs scripts, so it gets no CSP.
_DOCS_PATHS = ("/api/docs", "/api/openapi.json")


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = set_request_id(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            access_log.info(
                "request",
                extra={"method": scope.get("method"), "path": scope.get("path"),
                       "status": status_holder["status"],
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            reset_request_id(token)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_docs = scope.get("path", "").startswith(_DOCS_PATHS)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in API_SECURITY_HEADERS:
                    if name == b"content-security-policy" and is_docs:
                        continue
                    if name not in present:
                        headers.append((name, value))
                # API data (incl. personal data) must not be cached by browsers or proxies.
                if b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
