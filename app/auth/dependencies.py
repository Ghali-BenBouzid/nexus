from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.repository import get_user_by_id
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    try:
        user_id = decode_access_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    current_user = get_user_by_id(db=db, id=int(user_id))
    if current_user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return current_user
