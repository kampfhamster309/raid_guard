from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from ..auth import create_token, record_failure, too_many_failures, verify_credentials
from ..dependencies import get_pool

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
async def get_token(
    form: OAuth2PasswordRequestForm = Depends(),
    pool=Depends(get_pool),
):
    if too_many_failures(form.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed logins — wait a minute and try again",
        )
    row = await verify_credentials(pool, form.username, form.password)
    if row is None:
        record_failure(form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_token(row["username"], row["role"], row["password_hash"]))
