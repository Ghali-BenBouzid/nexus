import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


def create_access_token(user_id: int) -> str:
    expiry = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expiry},
        key=settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_access_token(token: str) -> int:
    """The user id in a valid token. Raises ``jwt.PyJWTError`` for a malformed,
    tampered or expired token, and ``ValueError`` for a non-numeric subject."""
    claims = jwt.decode(
        token,
        key=settings.secret_key,
        algorithms=[settings.algorithm],
        options={"require": ["exp", "sub"]},
    )
    return int(claims["sub"])


def new_invite_token() -> tuple[str, str]:
    """A fresh invite secret and its hash. The raw token only ever lives in the
    link handed to the visitor; the database stores the hash."""
    token = secrets.token_urlsafe(32)
    return token, hash_invite_token(token)


def hash_invite_token(token: str) -> str:
    # A plain SHA-256 is enough here, unlike passwords: the token is 256 random
    # bits, so there is nothing to brute-force, and a deterministic hash lets us
    # look the account up directly.
    return hashlib.sha256(token.encode()).hexdigest()
