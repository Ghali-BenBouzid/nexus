from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.dependencies import get_current_user
from app.auth.schemas import Token, UserRegister, UserResponse
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/auth")


@router.post(path="/register", status_code=201, response_model=UserResponse)
async def register(register_data: UserRegister, db: AsyncSession = Depends(get_db)):
    user = await service.register(
        db=db, email=register_data.email, password=register_data.password
    )

    return user


@router.post(path="/login", status_code=200, response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)
):
    access_token = await service.login(
        db=db, email=form_data.username, password=form_data.password
    )

    return Token(access_token=access_token)


@router.get("/me", status_code=200, response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
