from datetime import datetime
from typing import Any

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


class QueryEventResponse(BaseSchema):
    """One agent progress event for the live feed; ``id`` is the poll cursor."""

    id: int
    type: str
    message: str
    data: dict[str, Any] | None = None
    created_at: datetime


class ReviseRequest(BaseModel):
    # Optional reason for rejecting the plan; the planner revises accordingly.
    feedback: str = ""


class QueryDetail(BaseSchema):
    """Single-query view: the full result once terminal."""

    id: int
    prompt: str
    status: QueryStatus
    report: str | None
    error: str | None
    plan: list[str] | None = None  # proposed sub-questions while awaiting_plan
    sources: list[Source]  # cited sources backing the report
    consulted_sources: list[Source] = []  # full provenance/audit trail
    gaps: list[str]
    created_at: datetime
    completed_at: datetime | None
