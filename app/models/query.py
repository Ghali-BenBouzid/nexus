import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class QueryStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class QueryKind(enum.StrEnum):
    """What produced this run, which is also what the user gets out of it."""

    chat = "chat"  # one turn of a conversation: the answer is the assistant message
    deep_research = "deep_research"  # a background run whose report is an artifact
    fact_check = "fact_check"  # a document checked against the web, also an artifact

    @property
    def is_artifact(self) -> bool:
        return self is not QueryKind.chat


class Query(Base):
    """One run of the agents, whatever started it.

    A chat turn, a deep research run and a fact check differ in what they produce
    and where the user finds it, not in what they need from the system: an owner,
    a status, a heartbeat, a live event feed, a stop button and a bill. So they
    are one row with a ``kind``, and everything built around a run works for all
    three without being written three times.
    """

    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The conversation this run belongs to. Null for a one-shot API run, which
    # has no thread around it.
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Loaded only where asked for (selectinload), so a query that forgets to
    # ask fails loudly instead of lazy-loading inside an async session.
    conversation: Mapped["Conversation | None"] = relationship(lazy="raise")
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default=QueryKind.chat, index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # The document a fact check reads, so a second check of it can be refused
    # while the first is working. Null on every other kind of run. use_alter:
    # it closes a loop (a document belongs to a message, a message to a run).
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_queries_document_id",
        ),
        nullable=True,
    )
    # A short, human title for the artifact this run produces, named by whoever
    # started it. Null on a chat turn, which has no artifact.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, name="query_status"),
        default=QueryStatus.pending,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The finished report, on a run that produces one (deep research, fact check).
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The supervisor's answer, on a chat turn. Also copied onto the message.
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The same reply in the parts it was written in: what the supervisor said
    # before each round of tool calls, then its answer. Null on older turns.
    reply_parts: Mapped[list[str] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    # Real JSONB in Postgres; plain JSON in the aiosqlite test suite.
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Refreshed every few seconds while a job works on the query, so the UI can
    # tell a long step from a dead job and a worker can reap jobs that died.
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def conversation_public_id(self) -> uuid.UUID | None:
        """The conversation as the API names it (Conversation.public_id)."""
        return self.conversation.public_id if self.conversation else None


class QueryEvent(Base):
    """One agent progress event for a query, persisted so a polling client can
    tail the live feed. The autoincrement ``id`` is the natural cursor: clients
    ask for events ``after`` the last id they saw. Rows are append-only and cheap;
    a finished run leaves a small, ordered audit trail of what the agents did."""

    __tablename__ = "query_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured payload (index/total/sub_question/tool args) the feed renders;
    # plain JSON in the aiosqlite test suite, real JSONB in Postgres.
    data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
