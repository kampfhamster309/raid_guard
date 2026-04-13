from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from ..auth import create_token, get_user_row, verify_credentials
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
    if not await verify_credentials(pool, form.username, form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row = await get_user_row(pool, form.username)
    role = row["role"] if row else "viewer"
    return TokenResponse(access_token=create_token(form.username, role))
