from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"])


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(secret=plain_password, hash=hashed_password)


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
