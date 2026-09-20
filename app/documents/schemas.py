from datetime import datetime

from pydantic import BaseModel

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
    created_at: datetime


class FactCheckRequest(BaseModel):
    # Optional: which part of the document, or which kind of claim, to
    # concentrate on. Empty means check whatever the document rests on.
    focus: str = ""
