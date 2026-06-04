from pydantic import BaseModel

from app.schemas.base import BaseSchema


class UserRegister(BaseModel):
    email: str
    password: str


class UserResponse(BaseSchema):
    id: int
    email: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
