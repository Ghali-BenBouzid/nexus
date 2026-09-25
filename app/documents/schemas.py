from datetime import datetime

from app.models.document import DocumentStatus
from app.schemas.base import BaseSchema


class DocumentSummary(BaseSchema):
    """An uploaded document as the interface lists it. The text is not sent: it
    can be long, and the thread only needs to show what is attached."""

    id: int
    message_id: int | None = None  # the message it was sent with, if any
    filename: str
    media_type: str
    size_bytes: int
    pages: int | None
    chars: int
    truncated: bool  # the file was longer than max_document_chars
    ocr: bool  # read off pictures of pages, so the text may contain mistakes
    status: DocumentStatus  # reading until its job has turned it into text
    error: str | None = None  # why it could not be read
    created_at: datetime
