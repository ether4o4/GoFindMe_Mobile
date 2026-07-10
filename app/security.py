"""Single-user authentication: Argon2id password + opaque bearer tokens.

Tokens are random, stored only in process memory (a stolen DB yields no live
session), and accepted via the Authorization header or a cookie (the latter so
EventSource/SSE can authenticate without putting the token in a URL).
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, status
from passlib.context import CryptContext

from . import db
from .config import settings
from .util import audit, now_iso

# Prefer Argon2id; fall back to pure-Python pbkdf2_sha256 when the argon2 backend
# isn't available (e.g. the Android/Chaquopy build, or if it fails to bundle into
# a packaged desktop build). Existing hashes stay verifiable while their scheme
# is present.
try:
    import argon2 as _argon2  # noqa: F401

    _SCHEMES = ["argon2", "pbkdf2_sha256"]
except Exception:  # pragma: no cover - depends on the install
    _SCHEMES = ["pbkdf2_sha256"]

_pwd = CryptContext(schemes=_SCHEMES, deprecated="auto")

COOKIE_NAME = "gfm_token"

# token -> expiry epoch seconds
_sessions: dict[str, float] = {}

# crude login rate limiting: list of recent failure timestamps
_login_failures: list[float] = []
_MAX_FAILURES = 8
_FAIL_WINDOW = 300  # seconds


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, pw_hash: str) -> bool:
    try:
        return _pwd.verify(password, pw_hash)
    except Exception:
        return False


def setup_complete() -> bool:
    return db.query_one("SELECT 1 FROM app_user WHERE id=1") is not None


def create_user(username: str, password: str) -> None:
    if setup_complete():
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup already completed")
    if len(password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be at least 8 characters")
    db.execute(
        "INSERT INTO app_user (id, username, pw_hash, created_at) VALUES (1, ?, ?, ?)",
        (username.strip()[:64], hash_password(password), now_iso()),
    )
    audit("audit", "auth", "user created", username=username)


def _rate_limited() -> bool:
    cutoff = time.time() - _FAIL_WINDOW
    _login_failures[:] = [t for t in _login_failures if t > cutoff]
    return len(_login_failures) >= _MAX_FAILURES


def login(username: str, password: str) -> dict:
    if _rate_limited():
        audit("warn", "auth", "login rate limited")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts; wait a few minutes")
    row = db.query_one("SELECT username, pw_hash FROM app_user WHERE id=1")
    if not row or row["username"] != username or not verify_password(password, row["pw_hash"]):
        _login_failures.append(time.time())
        audit("warn", "auth", "login failed", username=username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = secrets.token_urlsafe(32)
    ttl = settings().token_ttl_days * 86400
    _sessions[token] = time.time() + ttl
    audit("audit", "auth", "login ok", username=username)
    return {"token": token, "expires_in": ttl}


def logout(token: str) -> None:
    _sessions.pop(token, None)


def _valid(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if exp < time.time():
        _sessions.pop(token, None)
        return False
    return True


async def require_auth(
    authorization: str | None = Header(default=None),
    gfm_token: str | None = Cookie(default=None),
) -> str:
    """FastAPI dependency. Returns the active token or raises 401."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    token = token or gfm_token
    if not _valid(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return token  # type: ignore[return-value]


# Convenience dependency object
Auth = Depends(require_auth)
