"""Backend-enforced write protection for the public demo.

* REVIEWER_PASSCODE (env only)   -> required in header `X-Reviewer-Passcode` for every
  faculty action (approve / edit / reject / reopen).
* ADMIN_RESET_TOKEN (env only)   -> required in header `X-Admin-Token` for the demo reset.
  Must differ from the reviewer passcode; the reset endpoint does not exist (404) when unset.

Secrets are read from the environment at request time, never hard-coded, never logged,
and compared in constant time. If REVIEWER_PASSCODE is unset, writes are DISABLED (fail
closed) rather than open. Repeated failures from one client are rate-limited.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import threading
import time

from fastapi import HTTPException, Request

MAX_FAILURES = 8
WINDOW_S = 600

_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


def _trusted_proxies() -> list:
    """TRUSTED_PROXIES (env, read per request like the secrets): comma-separated IPs or CIDR ranges of
    reverse proxies in front of this server. Empty (the default) = trust no forwarded headers."""
    nets = []
    for part in os.environ.get("TRUSTED_PROXIES", "").split(","):
        try:
            if part.strip():
                nets.append(ipaddress.ip_network(part.strip(), strict=False))
        except ValueError:
            continue  # a malformed entry is ignored, never treated as "trust everything"
    return nets


def _in(ip: str, nets: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def _client_key(request: Request) -> str:
    """Rate-limit identity. X-Forwarded-For is client-controlled, so it is used only when the direct
    peer is a configured trusted proxy; then the right-most address that is not a trusted proxy is the
    client. Otherwise the direct peer address is used, and a spoofed header changes nothing."""
    direct = request.client.host if request.client else "unknown"
    nets = _trusted_proxies()
    if not nets or not _in(direct, nets):
        return direct
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _in(hop, nets):
            return hop
    return direct


def _check_rate(key: str) -> None:
    now = time.monotonic()
    with _lock:
        recent = [t for t in _failures.get(key, []) if now - t < WINDOW_S]
        _failures[key] = recent
        if len(recent) >= MAX_FAILURES:
            raise HTTPException(429, "Too many wrong passcode attempts. Try again in a few minutes.")


def _record_failure(key: str) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.monotonic())


def reset_rate_limits() -> None:  # used by tests
    with _lock:
        _failures.clear()


def _matches(supplied: str | None, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def require_reviewer(request: Request) -> None:
    expected = os.environ.get("REVIEWER_PASSCODE", "")
    if not expected:
        raise HTTPException(503, "Faculty actions are disabled: REVIEWER_PASSCODE is not configured on the server.")
    key = _client_key(request)
    _check_rate(key)
    if not _matches(request.headers.get("x-reviewer-passcode"), expected):
        _record_failure(key)
        raise HTTPException(401, "Reviewer passcode required (or incorrect).")


def require_admin(request: Request) -> None:
    expected = os.environ.get("ADMIN_RESET_TOKEN", "")
    if not expected or expected == os.environ.get("REVIEWER_PASSCODE", ""):
        # Unset, or misconfigured to equal the reviewer passcode: the reset does not exist.
        raise HTTPException(404, "Not Found")
    key = _client_key(request)
    _check_rate(key)
    if not _matches(request.headers.get("x-admin-token"), expected):
        _record_failure(key)
        raise HTTPException(401, "Admin token required (or incorrect).")


def writes_enabled() -> bool:
    return bool(os.environ.get("REVIEWER_PASSCODE"))
