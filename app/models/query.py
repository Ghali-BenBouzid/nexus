import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class QueryStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, name="query_status"),
        default=QueryStatus.pending,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[str | None] = mapped_column(Text, nullable=True)
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
