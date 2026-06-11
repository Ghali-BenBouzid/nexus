from datetime import datetime

from pydantic import BaseModel

from app.agents.schemas import Source
from app.models.query import QueryStatus
from app.schemas.base import BaseSchema


class QueryCreate(BaseModel):
    prompt: str


class QueryResponse(BaseSchema):
    """List/create view: just lifecycle, no heavy result payload."""

    id: int
    prompt: str
    status: QueryStatus
    created_at: datetime


class QueryDetail(BaseSchema):
    """Single-query view: the full result once terminal."""

    id: int
    prompt: str
    status: QueryStatus
    report: str | None
    error: str | None
    sources: list[Source]  # cited sources backing the report
    consulted_sources: list[Source] = []  # full provenance/audit trail
    gaps: list[str]
    created_at: datetime
    completed_at: datetime | None
