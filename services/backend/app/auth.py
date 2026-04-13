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
JWT payload: ``{"sub": username, "role": role, "exp": ...}``

Backward compatibility
----------------------
Tokens issued before RAID-020 have no ``role`` claim and are treated as
``viewer`` on decode (safest default — forces re-login after upgrade).
"""

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

JWT_SECRET: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS: int = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

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


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── DB helpers ────────────────────────────────────────────────────────────────


async def get_user_row(pool, username: str) -> dict | None:
    """Return the users row as a dict, or None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username, password_hash, role FROM users WHERE username = $1",
            username,
        )
    return dict(row) if row else None


async def verify_credentials(pool, username: str, password: str) -> bool:
    """Constant-time credential check against the users table."""
    row = await get_user_row(pool, username)
    if row is None:
        # Run a dummy verification so timing is similar regardless of existence.
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return False
    return verify_password(password, row["password_hash"])


# ── Token helpers ─────────────────────────────────────────────────────────────


def create_token(username: str, role: str = "admin") -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> str:
    """Decode and validate *token*; return the username.  Raises 401 on failure."""
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise _UNAUTHORIZED
        return username
    except pyjwt.PyJWTError:
        raise _UNAUTHORIZED


# ── CurrentUser dataclass ─────────────────────────────────────────────────────


@dataclass
class CurrentUser:
    username: str
    role: str  # "admin" | "viewer"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _decode_current_user(token: str) -> CurrentUser:
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise _UNAUTHORIZED
        role: str = payload.get("role", "viewer")
        return CurrentUser(username=username, role=role)
    except pyjwt.PyJWTError:
        raise _UNAUTHORIZED


# ── FastAPI dependencies ──────────────────────────────────────────────────────


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Decode token and return a CurrentUser.  Used by require_admin and /users/me."""
    return _decode_current_user(token)


async def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """Validate token and return username.  Any authenticated role is accepted."""
    return _decode_current_user(token).username


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> str:
    """Validate token and require admin role.  Returns username.  Raises 403 for viewers."""
    if not current_user.is_admin:
        raise _FORBIDDEN
    return current_user.username


# ── Legacy env-var helper (kept for any remaining unit tests) ─────────────────

# These module-level constants are read from env at import time.  They are used
# only for the admin seed on first startup; login always goes through the DB.
ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
