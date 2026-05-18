from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session

from app.auth.repository import create_user, get_user_by_email
from app.auth.schemas import UserLogin, UserRegister
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User


def register(db: Session, register_data: UserRegister) -> User:
    if get_user_by_email(db, email=register_data.email) is not None:
        raise HTTPException(status_code=409, detail="User already exists")

    hashed_password = hash_password(register_data.password)

    user = create_user(db, email=register_data.email, hashed_password=hashed_password)

    return user


def login(db: Session, login_data: UserLogin) -> str:
    user = get_user_by_email(db, email=login_data.email)

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    payload = {"sub": str(user.id)}
    access_token = create_access_token(payload=payload)
    return access_token
