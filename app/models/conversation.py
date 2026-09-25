import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class Conversation(Base):
    """A chat thread: an ordered list of messages owned by one user. The title is
    filled later by the light titling model (Phase 4.5 step 1); until then it is
    null and the UI falls back to the first message."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What everything outside the database calls this conversation: the URL and
    # every API response. The integer id counts up across every account, so a
    # link to /chat/26 told anyone how many chats everyone had had, and invited
    # guessing the next one; this reveals nothing and cannot be guessed.
    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, index=True, nullable=False, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Bumped whenever a message is added, so the sidebar can sort by recency.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """One turn in a conversation. Each assistant message links to the ``Query``
    that tracks its turn via ``query_id``: a research report, or a direct reply
    (also copied into ``content``). Older replies have no query. The research is
    always reached through the message (no conversation_id on the query)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    query_id: Mapped[int | None] = mapped_column(
        ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )
    # A question panel. On an assistant message, the questions its turn asked
    # (question, options); on the user's answer, the questions with what was
    # chosen (question, answer, None when skipped). Plain JSON in the tests.
    ask: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
