"""Uploading a document: read it, turn it into text, keep both.

The text goes in the database (the agents read it), the original file goes in the
bucket (the interface shows it). Everything that can go wrong for a reason the
user can act on, an unreadable file, one too large, too many in a conversation,
raises ``UploadError`` with a message meant to be shown as it is.
"""

import asyncio

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.documents import repository, storage
from app.documents.parser import ParseError, parse
from app.models.document import Document

_CHUNK = 1024 * 1024


class UploadError(Exception):
    """The upload was refused. The message is shown to the user."""


async def _read(upload: UploadFile) -> bytes:
    """The file's bytes, refusing anything past the size cap. Read in chunks so an
    oversized upload is stopped instead of held whole in memory."""
    limit = int(settings.max_upload_mb * 1024 * 1024)
    chunks: list[bytes] = []
    size = 0
    while chunk := await upload.read(_CHUNK):
        size += len(chunk)
        if size > limit:
            raise UploadError(
                f"{upload.filename} is larger than the "
                f"{settings.max_upload_mb:g} MB limit."
            )
        chunks.append(chunk)
    if not size:
        raise UploadError("The file is empty.")
    return b"".join(chunks)


async def upload(
    db: AsyncSession,
    upload_file: UploadFile,
    *,
    conversation_id: int,
    user_id: int,
) -> Document:
    if not storage.available():
        raise UploadError("Document uploads are not configured on this server.")

    count = await repository.count_for_conversation(db, conversation_id)
    if count >= settings.max_documents_per_conversation:
        raise UploadError(
            "This conversation already has "
            f"{settings.max_documents_per_conversation} documents. "
            "Remove one before adding another."
        )

    filename = (upload_file.filename or "document").strip()
    data = await _read(upload_file)
    try:
        # Off the event loop: reading a PDF is seconds of CPU, and run inline it
        # froze every other request on this server until it was done.
        parsed = await asyncio.to_thread(parse, filename, data)
    except ParseError as exc:
        raise UploadError(str(exc)) from exc

    text = parsed.text[: settings.max_document_chars]

    media_type = upload_file.content_type or "application/octet-stream"
    key = storage.key_for(user_id, filename)
    try:
        await storage.put(key, data, media_type)
    except storage.StorageError as exc:
        raise UploadError("The file could not be stored. Try again.") from exc

    document = Document(
        conversation_id=conversation_id,
        user_id=user_id,
        filename=filename,
        media_type=media_type,
        size_bytes=len(data),
        pages=parsed.pages,
        text=text,
        ocr=parsed.ocr,
        storage_key=key,
    )
    try:
        return await repository.add(db, document)
    except Exception:
        # Nothing points at the object any more, so leave nothing behind.
        await _forget(key)
        raise


async def delete(db: AsyncSession, document: Document) -> None:
    key = document.storage_key
    await repository.remove(db, document)
    await _forget(key)


async def _forget(key: str | None) -> None:
    """Best effort: a file left in the bucket is waste, not a failure the user
    should see, and the row is already gone."""
    if not key:
        return
    try:
        await storage.delete(key)
    except storage.StorageError:
        pass


async def forget_account(user_id: int) -> int:
    """Remove every file this account uploaded, and say how many. Its rows go
    with the account through the database's cascade; its objects would otherwise
    stay in the bucket forever."""
    if not storage.available():
        return 0
    return await storage.delete_prefix(storage.prefix_for(user_id))


def truncated(document: Document) -> bool:
    return len(document.text) >= settings.max_document_chars
