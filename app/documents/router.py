from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.conversations import repository as conversations
from app.db.session import get_db
from app.documents import repository, service, storage
from app.documents.schemas import DocumentSummary
from app.models.document import Document
from app.models.user import User

router = APIRouter(tags=["documents"])


def summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        pages=document.pages,
        chars=len(document.text),
        truncated=service.truncated(document),
        created_at=document.created_at,
    )


async def _own_document(document_id: int, db: AsyncSession, user: User) -> Document:
    document = await repository.get_for_user(db, document_id, user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.post(
    "/conversations/{conversation_id}/documents",
    response_model=DocumentSummary,
    status_code=201,
)
async def upload(
    conversation_id: int,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentSummary:
    conversation = await conversations.get_conversation(db, conversation_id, user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    try:
        document = await service.upload(
            db, file, conversation_id=conversation_id, user_id=user.id
        )
    except service.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return summary(document)


@router.get(
    "/conversations/{conversation_id}/documents",
    response_model=list[DocumentSummary],
)
async def list_documents(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentSummary]:
    conversation = await conversations.get_conversation(db, conversation_id, user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    documents = await repository.list_for_conversation(db, conversation_id)
    return [summary(document) for document in documents]


@router.get("/documents/{document_id}/file")
async def download(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """The original file, so the interface can show the document itself."""
    document = await _own_document(document_id, db, user)
    if not document.storage_key:
        raise HTTPException(status_code=404, detail="The original file is gone.")
    try:
        data = await storage.get(document.storage_key)
    except storage.StorageError as exc:
        raise HTTPException(status_code=502, detail="File storage failed.") from exc
    return Response(
        content=data,
        media_type=document.media_type,
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    document = await _own_document(document_id, db, user)
    await service.delete(db, document)
