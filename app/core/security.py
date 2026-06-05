import asyncio
from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"])


async def hash_password(password: str) -> str:
    # bcrypt is CPU-bound and blocking; run it off the event loop.
    return await asyncio.to_thread(pwd_context.hash, password)


async def verify_password(plain_password: str, hashed_password: str) -> bool:
    # bcrypt is CPU-bound and blocking; run it off the event loop.
    return await asyncio.to_thread(pwd_context.verify, plain_password, hashed_password)


def create_access_token(payload: dict) -> str:
    data = payload.copy()  # avoiding mutating payload directly

    expiry = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    data["exp"] = expiry

    return jwt.encode(
        claims=data, key=settings.secret_key, algorithm=settings.algorithm
    )


def decode_access_token(token: str) -> str:
    claims = jwt.decode(
        token=token, key=settings.secret_key, algorithms=[settings.algorithm]
    )

    return claims["sub"]
