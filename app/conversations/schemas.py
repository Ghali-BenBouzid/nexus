from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.schemas import Source
from app.core.config import Effort
from app.documents.schemas import DocumentSummary
from app.models.conversation import MessageRole
from app.models.query import QueryStatus
from app.research.schemas import ArtifactSummary, QueryEventResponse
from app.schemas.base import BaseSchema

# What the user switched the composer to for this message. Never an order: it
# tells the supervisor what they are after, and the supervisor decides what the
# message actually calls for.
Mode = Literal["answer", "deep", "factcheck"]


class ConversationCreate(BaseModel):
    # The first user message; creating a conversation and posting its first
    # message is one call, so a new chat is a single round-trip. Empty creates
    # the conversation and nothing else, which is what a file attached before
    # the first message needs: a file belongs to a conversation, so the
    # conversation has to exist before the message that carries it.
    prompt: str = ""
    document_ids: list[int] = []
    mode: Mode = "answer"
    effort: Effort = "medium"


class Answered(BaseModel):
    """One question of a panel, with what the user chose; None if skipped."""

    question: str
    answer: str | None = None


class MessageCreate(BaseModel):
    content: str
    # Files uploaded into this conversation and sent with this message.
    document_ids: list[int] = []
    mode: Mode = "answer"
    # How hard the supervisor thinks on this turn, picked in the composer. Deep
    # runs and fact checks keep their own (settings), whatever it says.
    effort: Effort = "medium"
    # Sent from the question panel: the message's text is written from these.
    answers: list[Answered] | None = None


class ConversationSummary(BaseSchema):
    """Sidebar row."""

    id: UUID = Field(validation_alias="public_id")
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageQuery(BaseModel):
    """The research run a message carries, rendered for the thread view."""

    status: QueryStatus
    title: str | None = None  # the artifact's title, on a run that makes one
    report: str | None
    reply: str | None = None  # the supervisor's answer, on a chat turn
    reply_parts: list[str] | None = None  # the same, in the parts it was written in
    error: str | None
    stopped: bool = False  # failed because the user stopped it, not broken
    sources: list[Source]
    gaps: list[str]
    # The turn's feed and how long it took, so a reloaded thread shows the work
    # between the parts of the reply the way it did live.
    events: list[QueryEventResponse] = []
    created_at: datetime | None = None
    completed_at: datetime | None = None
    # The composer mode the turn was sent in; None on turns older than it.
    mode: str | None = None


class MessageResponse(BaseModel):
    id: int
    role: MessageRole
    content: str
    query_id: int | None
    created_at: datetime
    # The files sent with this message, shown on the bubble that carries them.
    documents: list[DocumentSummary] = []
    # Present on an assistant message that carries a research run.
    query: MessageQuery | None = None
    # The question panel: asked, on an assistant message; answered, on a user's.
    ask: list[dict] | None = None


class ConversationDetail(BaseSchema):
    """The full thread: its messages, the documents uploaded into it, and the
    reports it has produced (which finish long after the turn that asked)."""

    id: UUID
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]
    documents: list[DocumentSummary] = []
    artifacts: list[ArtifactSummary] = []
