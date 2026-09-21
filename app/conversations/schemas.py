from datetime import datetime

from pydantic import BaseModel

from app.agents.schemas import Source
from app.documents.schemas import DocumentSummary
from app.models.conversation import MessageRole
from app.models.query import QueryStatus
from app.research.schemas import ArtifactSummary
from app.schemas.base import BaseSchema


class ConversationCreate(BaseModel):
    # The first user message; creating a conversation and posting its first
    # message is one call, so a new chat is a single round-trip. Empty creates
    # the conversation and nothing else, which is what a file attached before
    # the first message needs: a file belongs to a conversation, so the
    # conversation has to exist before the message that carries it.
    prompt: str = ""
    document_ids: list[int] = []
    # Send this first message as deep research rather than as a chat turn.
    deep: bool = False


class MessageCreate(BaseModel):
    content: str
    # Files uploaded into this conversation and sent with this message.
    document_ids: list[int] = []
    # Answer this message with a deep research run instead of the supervisor.
    # The mode is the user's choice, per message, not the supervisor's judgement.
    deep: bool = False


class ConversationSummary(BaseSchema):
    """Sidebar row."""

    id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageQuery(BaseModel):
    """The research run a message carries, rendered for the thread view."""

    kind: str  # chat, deep_research, fact_check: what this turn produced
    status: QueryStatus
    title: str | None = None  # the artifact's title, on a run that makes one
    report: str | None
    reply: str | None = None  # the supervisor's answer, on a chat turn
    error: str | None
    stopped: bool = False  # failed because the user stopped it, not broken
    sources: list[Source]
    gaps: list[str]


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


class ConversationDetail(BaseSchema):
    """The full thread: its messages, the documents uploaded into it, and the
    reports it has produced (which finish long after the turn that asked)."""

    id: int
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]
    documents: list[DocumentSummary] = []
    artifacts: list[ArtifactSummary] = []
