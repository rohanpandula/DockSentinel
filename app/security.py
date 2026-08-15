"""Request-level protections: cross-site request blocking and optional basic auth.

DockSentinel historically had no authentication at all, so any web page an
operator visited could POST to it (CSRF) and anyone on the network could read
secrets. Two cheap defenses that need no new frameworks:

1. Origin check — state-changing requests whose ``Origin``/``Referer`` header
   points at a different host than the request target are rejected with 403.
   Browsers always attach ``Origin`` to cross-site POSTs; CLI/tests send none.
2. Optional HTTP basic auth — enabled by setting ``BASIC_AUTH_USER`` and
   ``BASIC_AUTH_PASSWORD``. ``/api/health`` stays open for Docker HEALTHCHECK.
"""
from __future__ import annotations

import hmac
import os
from urllib.parse import urlsplit

from flask import Flask, Response, abort, request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HEALTH_PATH = "/api/health"


def _same_origin(header_value: str, host: str) -> bool:
    parsed = urlsplit(header_value)
    return bool(parsed.netloc) and parsed.netloc.lower() == host.lower()


def _reject_cross_site_writes() -> None:
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    host = request.host
    if origin:
        if origin == "null" or not _same_origin(origin, host):
            abort(403, description="cross-site request rejected")
        return
    if referer and not _same_origin(referer, host):
        abort(403, description="cross-site request rejected")


def _basic_auth_guard(user: str, password: str):
    def _check() -> Response | None:
        if request.path == _HEALTH_PATH:
            return None
        auth = request.authorization
        if (
            auth is not None
            and auth.type == "basic"
            and hmac.compare_digest(auth.username or "", user)
            and hmac.compare_digest(auth.password or "", password)
        ):
            return None
        return Response(
            "authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="DockSentinel"'},
        )

    return _check


def install_security(app: Flask) -> None:
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.before_request(_reject_cross_site_writes)

    user = (os.getenv("BASIC_AUTH_USER") or "").strip()
    password = os.getenv("BASIC_AUTH_PASSWORD") or ""
    if user and password:
        app.before_request(_basic_auth_guard(user, password))
        app.config["BASIC_AUTH_ENABLED"] = True
    else:
        app.config["BASIC_AUTH_ENABLED"] = False
