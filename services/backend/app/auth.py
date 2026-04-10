"""
JWT authentication for the raid_guard backend.

Single admin user: credentials are set via ADMIN_USERNAME / ADMIN_PASSWORD
environment variables.  No DB user table is needed until RAID-020.

If JWT_SECRET is not set, a random secret is generated at startup — tokens
are then invalidated on every restart.  Set JWT_SECRET in .env for
persistent sessions.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
JWT_SECRET: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS: int = int(os.environ.get("JWT_EXPIRY_HOURS", "24"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def verify_admin(username: str, password: str) -> bool:
    """Constant-time comparison — avoids timing attacks."""
    if not ADMIN_PASSWORD:
        return False  # no password configured → deny all
    return secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(
        password, ADMIN_PASSWORD
    )


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> str:
    """Decode and validate *token*; return the username.  Raises HTTPException on failure."""
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str | None = payload.get("sub")
        if not username:
            raise _UNAUTHORIZED
        return username
    except pyjwt.PyJWTError:
        raise _UNAUTHORIZED


async def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI dependency: validates the Bearer token and returns the username."""
    return decode_token(token)
