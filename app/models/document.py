import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(enum.StrEnum):
    """Where a file is in being turned into text. The upload only stores it; a
    job reads it, because reading a scan takes long enough that a user reloads
    the page, and a read that lived in the upload's request died with it."""

    reading = "reading"
    ready = "ready"
    failed = "failed"


class Document(Base):
    """A file the user uploaded into a conversation.

    The extracted text lives here, because that is what the agents read. The
    original file lives in object storage under ``storage_key`` so the interface
    can show the real document next to what was said about it.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Kept alongside the conversation's owner so a document can be authorized and
    # its storage key namespaced without loading the conversation.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The user message this file was sent with, when it was attached in the
    # composer rather than added to the conversation on its own. It is what lets
    # the thread show the file on the message it came with, the way it looked
    # when it was sent.
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)  # PDFs only
    # Empty until the file has been read.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"),
        nullable=False,
        default=DocumentStatus.ready,
        server_default=DocumentStatus.ready.value,
    )
    # Why the file could not be read, worded for the user.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The text was read off pictures of pages, so it carries OCR mistakes.
    ocr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Where the original file sits in the bucket. Null once storage is unavailable
    # or the file was dropped; the text still works on its own.
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
