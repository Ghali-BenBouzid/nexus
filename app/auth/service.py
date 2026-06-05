from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.repository import create_user, get_user_by_email
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User


async def register(db: AsyncSession, email: str, password: str) -> User:
    if await get_user_by_email(db, email=email) is not None:
        raise HTTPException(status_code=409, detail="User already exists")

    hashed_password = await hash_password(password)

    user = await create_user(db, email=email, hashed_password=hashed_password)

    return user


async def login(db: AsyncSession, email: str, password: str) -> str:
    user = await get_user_by_email(db, email=email)

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not await verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {"sub": str(user.id)}
    access_token = create_access_token(payload=payload)
    return access_token
