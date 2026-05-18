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

    return jwt.encode(data, settings.secret_key, settings.algorithm)
