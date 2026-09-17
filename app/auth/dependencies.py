import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import get_user_by_id
from app.auth.security import decode_access_token
from app.auth.service import ACCESS_EXPIRED
from app.db.session import get_db
from app.models.user import User

# auto_error=False so a missing header is our 401 (FastAPI's default is a 403).
bearer = HTTPBearer(auto_error=False)

_INVALID = HTTPException(
    status_code=401,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> User:
    if credentials is None:
        raise _INVALID
    try:
        user_id = decode_access_token(credentials.credentials)
    except (jwt.PyJWTError, ValueError):
        raise _INVALID from None

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise _INVALID
    # Checked on every request, so an account that expires mid-session stops here
    # rather than when its access token runs out.
    if user.is_expired:
        raise HTTPException(status_code=403, detail=ACCESS_EXPIRED)
    return user
