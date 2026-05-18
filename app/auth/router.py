from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.schemas import Token, UserLogin, UserRegister, UserResponse
from app.db.session import get_db

router = APIRouter(prefix="/auth")


@router.post(path="/register", status_code=201, response_model=UserResponse)
def register(register_data: UserRegister, db: Session = Depends(get_db)):
    user = service.register(db=db, register_data=register_data)

    return user


@router.post(path="/login", status_code=200, response_model=Token)
def login(login_data: UserLogin, db: Session = Depends(get_db)):
    access_token = service.login(db=db, login_data=login_data)

    return Token(access_token=access_token)
