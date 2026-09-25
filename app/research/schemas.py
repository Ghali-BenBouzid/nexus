from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

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


class ArtifactSummary(BaseSchema):
    """One report the user keeps: a deep research run or a fact check. Listed
    across every conversation, because a background run finishes long after the
    thread that started it has moved on."""

    id: int
    kind: str
    conversation_id: UUID | None = Field(validation_alias="conversation_public_id")
    title: str | None
    prompt: str
    status: QueryStatus
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class QueryDetail(BaseSchema):
    """Single-query view: the full result once terminal."""

    id: int
    prompt: str
    title: str | None = None  # the artifact's title, on a run that makes one
    status: QueryStatus
    report: str | None
    reply: str | None = None  # the supervisor's answer, on a chat turn
    reply_parts: list[str] | None = None  # the same, in the parts it was written in
    # The questions a chat turn ended on, if it asked the user any.
    ask: list[dict] | None = None
    error: str | None
    stopped: bool = False  # failed because the user stopped it, not broken
    kind: str = "chat"
    sources: list[Source]  # cited sources backing the report or the reply
    consulted_sources: list[Source] = []  # full provenance/audit trail
    gaps: list[str]
    created_at: datetime
    completed_at: datetime | None
    # How long ago the job last showed signs of life (None before it starts). A
    # long step keeps it low; a job that died lets it grow.
    seconds_since_heartbeat: float | None = None
