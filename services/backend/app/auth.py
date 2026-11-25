"""
JWT authentication for the raid_guard backend (RAID-020: multi-user).

Users are stored in the ``users`` table with bcrypt-hashed passwords and a
``role`` of either ``admin`` or ``viewer``.  The first admin user is seeded
from the ``ADMIN_USERNAME`` / ``ADMIN_PASSWORD`` environment variables when
the users table is empty (see ``app.main._seed_admin``).

Roles
-----
admin   Full read + write access to all endpoints.
viewer  Read-only; write endpoints return 403.

Token format
------------
JWT payload: ``{"sub": username, "role": role, "pwf": fingerprint, "exp": ...}``

Every request re-checks the token against the ``users`` row: a deleted user,
or a token issued before the user's password changed (``pwf`` no longer
matches the stored hash), is rejected, and the role comes from the DB.  If the
DB is unreachable the signed claims are trusted, so the status page still
loads during a DB outage.
"""

import asyncio
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .dependencies import get_pool

logger = logging.getLogger(__name__)

JWT_SECRET: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS: int = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

# bcrypt only looks at the first 72 bytes (bcrypt 5 raises past that).
MAX_PASSWORD_BYTES = 72

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)
_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Admin role required",
)


# ── Password helpers ──────────────────────────────────────────────────────────
# bcrypt is deliberately slow (~0.25 s): callers run these via asyncio.to_thread
# so a login never stalls the event loop that also runs the ingestor.


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:  # longer than 72 bytes — can't match any stored hash
        return False


_DUMMY_HASH = hash_password("dummy")


# ── Failed-login limiter ──────────────────────────────────────────────────────

_MAX_FAILURES = 5
_FAILURE_WINDOW_S = 60.0
_failed_logins: dict[str, list[float]] = {}


def too_many_failures(username: str) -> bool:
    """True if *username* had ``_MAX_FAILURES`` failed logins in the last minute."""
    now = time.monotonic()
    recent = [t for t in _failed_logins.get(username, []) if now - t < _FAILURE_WINDOW_S]
    if recent:
        _failed_logins[username] = recent
    else:
        _failed_logins.pop(username, None)
    return len(recent) >= _MAX_FAILURES


def record_failure(username: str) -> None:
    # shortcut: per-process memory, cleared wholesale if spraying random usernames fills it;
    # move to Redis if the backend ever runs more than one worker.
    if len(_failed_logins) > 10_000:
        _failed_logins.clear()
    _failed_logins.setdefault(username, []).append(time.monotonic())


# ── DB helpers ────────────────────────────────────────────────────────────────


async def get_user_row(pool, username: str) -> dict | None:
    """Return the users row as a dict, or None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username, password_hash, role FROM users WHERE username = $1",
            username,
        )
    return dict(row) if row else None


async def verify_credentials(pool, username: str, password: str) -> dict | None:
    """Return the users row if the password matches, else None (similar timing either way)."""
    row = await get_user_row(pool, username)
    hashed = row["password_hash"] if row else _DUMMY_HASH
    ok = await asyncio.to_thread(verify_password, password, hashed)
    return row if ok and row else None


# ── Token helpers ─────────────────────────────────────────────────────────────


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_token(username: str, role: str = "admin", password_hash: str = "") -> str:
    payload = {
        "sub": username,
        "role": role,
        "pwf": _password_fingerprint(password_hash),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ── CurrentUser dataclass ─────────────────────────────────────────────────────


@dataclass
class CurrentUser:
    username: str
    role: str  # "admin" | "viewer"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


async def user_from_token(pool, token: str) -> CurrentUser:
    """Validate *token* and check it against the users table.  Raises 401."""
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.PyJWTError:
        raise _UNAUTHORIZED
    username: str | None = payload.get("sub")
    if not username:
        raise _UNAUTHORIZED

    try:
        row = await get_user_row(pool, username)
    except Exception as exc:
        logger.warning("Auth: users table unreachable (%s); trusting token claims", exc)
        return CurrentUser(username=username, role=payload.get("role", "viewer"))

    if row is None or payload.get("pwf") != _password_fingerprint(row["password_hash"]):
        raise _UNAUTHORIZED  # user deleted, or password changed since the token was issued
    return CurrentUser(username=row["username"], role=row["role"])


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def get_current_user(token: str = Depends(oauth2_scheme), pool=Depends(get_pool)) -> CurrentUser:
    """Decode token and return a CurrentUser.  Used by require_admin and /users/me."""
    return await user_from_token(pool, token)


async def require_auth(current_user: CurrentUser = Depends(get_current_user)) -> str:
    """Validate token and return username.  Any authenticated role is accepted."""
    return current_user.username


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> str:
    """Validate token and require admin role.  Returns username.  Raises 403 for viewers."""
    if not current_user.is_admin:
        raise _FORBIDDEN
    return current_user.username


# Read from env at import time; used only to seed the first admin on startup.
ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
