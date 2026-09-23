from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.auth.dependencies import get_current_user
from app.billing.service import ensure_budget
from app.conversations import repository as conversations
from app.db.session import get_db
from app.documents import repository, service, storage
from app.documents.schemas import DocumentSummary, FactCheckRequest
from app.models.document import Document
from app.models.query import QueryKind
from app.models.user import User
from app.research import repository as research_repository
from app.research.factcheck import run_fact_check_job
from app.research.schemas import ArtifactSummary

router = APIRouter(tags=["documents"])


def summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        message_id=document.message_id,
        filename=document.filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        pages=document.pages,
        chars=len(document.text),
        truncated=service.truncated(document),
        ocr=document.ocr,
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


@router.post(
    "/documents/{document_id}/fact-check",
    response_model=ArtifactSummary,
    status_code=202,
)
async def start_fact_check(
    document_id: int,
    payload: FactCheckRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ArtifactSummary:
    """Check this document against the web. The same sub-agent the supervisor
    calls, started from the document instead of from a sentence: it runs in the
    background and its report lands in Outputs like any other."""
    document = await _own_document(document_id, db, user)
    await ensure_budget(db, user)
    focus = (payload.focus if payload else "") or ""
    query = await research_repository.create_pending_query(
        db=db,
        user_id=user.id,
        prompt=focus or f"Fact check of {document.filename}",
        title=f"Fact check: {document.filename}",
        kind=QueryKind.fact_check,
        conversation_id=document.conversation_id,
    )
    await jobs.spawn(
        run_fact_check_job,
        query_id=query.id,
        document_id=document.id,
        focus=focus,
    )
    return ArtifactSummary.model_validate(query)


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
    name = quote(document.filename)
    return Response(
        content=data,
        media_type=document.media_type,
        # Headers are Latin-1, and a filename is whatever the user called it: an
        # en dash or an accent put raw into the header crashed the response. The
        # RFC 5987 form carries any name, and encoding it also means a quote in
        # the name cannot close the value early.
        headers={"Content-Disposition": f"inline; filename*=utf-8''{name}"},
    )


@router.delete("/documents/{document_id}", status_code=204)
async def delete(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    document = await _own_document(document_id, db, user)
    await service.delete(db, document)
