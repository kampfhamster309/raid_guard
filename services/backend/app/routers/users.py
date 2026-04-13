"""User management API (RAID-020).

Endpoints
---------
GET    /api/users           List all users (admin only)
GET    /api/users/me        Current user info (any authenticated role)
POST   /api/users           Create a user (admin only)
PUT    /api/users/{username}/password   Change a user's password (self or admin)
DELETE /api/users/{username}            Delete a user (admin only; cannot delete self)
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from ..auth import CurrentUser, get_current_user, hash_password, require_admin, verify_password
from ..dependencies import get_pool

router = APIRouter(prefix="/api/users", tags=["users"])


# ── Models ────────────────────────────────────────────────────────────────────


class UserOut(BaseModel):
    username: str
    role: str
    created_at: str


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = "viewer"

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        if v not in ("admin", "viewer"):
            raise ValueError("role must be 'admin' or 'viewer'")
        return v

    @field_validator("username")
    @classmethod
    def _non_empty_username(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("username must not be empty")
        return v.strip()

    @field_validator("password")
    @classmethod
    def _min_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _min_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("new_password must be at least 8 characters")
        return v


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserOut)
async def get_me(current_user: CurrentUser = Depends(get_current_user), pool=Depends(get_pool)):
    """Return the currently authenticated user's info."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT username, role, created_at::text FROM users WHERE username = $1",
            current_user.username,
        )
    if row is None:
        # Should not happen in normal operation; token is valid but user was deleted.
        raise HTTPException(status_code=404, detail="User not found")
    return UserOut(**dict(row))


@router.get("", response_model=list[UserOut])
async def list_users(
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """List all users ordered by creation date."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT username, role, created_at::text FROM users ORDER BY created_at"
        )
    return [UserOut(**dict(r)) for r in rows]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: CreateUserBody,
    pool=Depends(get_pool),
    _: str = Depends(require_admin),
):
    """Create a new user.  Username must be unique."""
    hashed = hash_password(body.password)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO users (username, password_hash, role) "
                "VALUES ($1, $2, $3) "
                "RETURNING username, role, created_at::text",
                body.username,
                hashed,
                body.role,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="Username already exists")
            raise
    return UserOut(**dict(row))


@router.put("/{username}/password", status_code=204)
async def change_password(
    username: str,
    body: ChangePasswordBody,
    pool=Depends(get_pool),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Change a user's password.  Users may change their own; admins may change any."""
    if username != current_user.username and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Cannot change another user's password")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password_hash FROM users WHERE username = $1", username
        )
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Non-admins must provide the current password even when changing their own.
    if not current_user.is_admin:
        if not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    new_hash = hash_password(body.new_password)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE username = $2",
            new_hash,
            username,
        )
    return Response(status_code=204)


@router.delete("/{username}", status_code=204)
async def delete_user(
    username: str,
    pool=Depends(get_pool),
    current_user: CurrentUser = Depends(get_current_user),
    _: str = Depends(require_admin),
):
    """Delete a user.  Admins cannot delete themselves."""
    if username == current_user.username:
        raise HTTPException(status_code=409, detail="Cannot delete your own account")

    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE username = $1", username)

    # asyncpg returns "DELETE N" — check N > 0.
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="User not found")

    return Response(status_code=204)
