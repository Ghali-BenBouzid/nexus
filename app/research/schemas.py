from datetime import datetime

from pydantic import BaseModel

from app.schemas.base import BaseSchema


class QueryCreate(BaseModel):
    prompt: str


class QueryResponse(BaseSchema):
    id: int
    prompt: str
    report: str | None
    created_at: datetime
