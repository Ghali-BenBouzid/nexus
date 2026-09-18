from datetime import datetime

from pydantic import BaseModel

from app.agents.schemas import Source
from app.documents.schemas import DocumentSummary
from app.models.conversation import MessageRole
from app.models.query import QueryStatus
from app.schemas.base import BaseSchema


class ConversationCreate(BaseModel):
    # The first user message; creating a conversation and posting its first
    # message is one call so a new chat is a single round-trip.
    prompt: str


class MessageCreate(BaseModel):
    content: str


class ConversationSummary(BaseSchema):
    """Sidebar row."""

    id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageQuery(BaseModel):
    """The research run a message carries, rendered for the thread view."""

    status: QueryStatus
    title: str | None = None  # the supervisor-given report title
    report: str | None
    reply: str | None = None  # the supervisor's direct answer, on an answer turn
    error: str | None
    stopped: bool = False  # failed because the user stopped it, not broken
    plan: list[str] | None = None  # proposed sub-questions while awaiting_plan
    sources: list[Source]
    gaps: list[str]


class MessageResponse(BaseModel):
    id: int
    role: MessageRole
    content: str
    query_id: int | None
    created_at: datetime
    # Present on an assistant message that carries a research run.
    query: MessageQuery | None = None


class ConversationDetail(BaseSchema):
    """The full thread: ordered messages, each with its report when it has one,
    and the documents uploaded into it."""

    id: int
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]
    documents: list[DocumentSummary] = []
