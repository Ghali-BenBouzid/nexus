from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
from app.billing.service import ensure_budget
from app.conversations import repository, service
from app.conversations.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    MessageCreate,
    MessageQuery,
    MessageResponse,
)
from app.db.session import get_db
from app.documents import repository as documents_repository
from app.documents.router import summary as document_summary
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.query import Query
from app.models.user import User
from app.research import repository as research_repository
from app.research.dependencies import get_model, get_search_backend
from app.research.repository import stopped_by_user
from app.research.router import _load_result

router = APIRouter(prefix="/conversations")


def _message_query(query: Query | None) -> MessageQuery | None:
    if query is None:
        return None
    result = _load_result(query.result, query.id)
    return MessageQuery(
        status=query.status,
        title=query.title,
        report=query.report,
        reply=query.reply,
        error=query.error,
        stopped=stopped_by_user(query),
        sources=result.sources if result else [],
        gaps=result.gaps if result else [],
        mode=query.mode,
    )


def _to_responses(
    messages: list[Message],
    queries: dict[int, Query],
    documents: list[Document],
) -> list[MessageResponse]:
    by_message: dict[int, list[Document]] = {}
    for document in documents:
        if document.message_id is not None:
            by_message.setdefault(document.message_id, []).append(document)
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            query_id=m.query_id,
            created_at=m.created_at,
            documents=[document_summary(d) for d in by_message.get(m.id, [])],
            query=_message_query(queries.get(m.query_id)) if m.query_id else None,
            ask=m.ask,
        )
        for m in messages
    ]


async def _detail(db: AsyncSession, conversation: Conversation) -> ConversationDetail:
    messages = await repository.list_messages(db, conversation.id)
    query_ids = [m.query_id for m in messages if m.query_id is not None]
    queries = await repository.queries_by_id(db, query_ids)
    documents = await documents_repository.list_for_conversation(db, conversation.id)
    artifacts = await research_repository.list_conversation_artifacts(
        db, conversation.id
    )
    return ConversationDetail(
        id=conversation.public_id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=_to_responses(messages, queries, documents),
        documents=[document_summary(d) for d in documents],
        artifacts=artifacts,
    )


@router.post("", response_model=ConversationDetail, status_code=201)
async def create(
    payload: ConversationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Any, not BaseChatModel: it is a pydantic model, and FastAPI would read
    # the annotation as a request body rather than a dependency.
    model: Any = Depends(get_model),
    backend: SearchBackend = Depends(get_search_backend),
):
    # Every message costs a call, so the budget is checked up front.
    await ensure_budget(db, current_user)
    conversation = await repository.create_conversation(db, current_user.id)
    # An empty prompt creates the conversation and nothing else: what a file
    # attached before the first message needs, since it has to be uploaded into
    # a conversation before the message that carries it can be sent.
    # A file is a message on its own, so files with no text still send.
    if payload.prompt.strip() or payload.document_ids:
        await service.submit_message(
            db,
            conversation,
            payload.prompt,
            model=model,
            backend=backend,
            background_tasks=background_tasks,
            document_ids=payload.document_ids,
            mode=payload.mode,
        )
    return await _detail(db, conversation)


@router.get("", response_model=list[ConversationSummary])
async def list_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await repository.list_conversations(db, current_user.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def detail(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await repository.get_conversation(
        db, conversation_id, current_user.id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await _detail(db, conversation)


@router.post("/{conversation_id}/messages", response_model=ConversationDetail)
async def add_message(
    conversation_id: UUID,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Any, not BaseChatModel: it is a pydantic model, and FastAPI would read
    # the annotation as a request body rather than a dependency.
    model: Any = Depends(get_model),
    backend: SearchBackend = Depends(get_search_backend),
):
    conversation = await repository.get_conversation(
        db, conversation_id, current_user.id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Text, files or both, but never neither: the client should not send one,
    # and an empty turn would hand the supervisor nothing to answer.
    if not payload.content.strip() and not payload.document_ids:
        raise HTTPException(status_code=422, detail="A message needs text or a file.")
    await ensure_budget(db, current_user)
    await service.submit_message(
        db,
        conversation,
        payload.content,
        model=model,
        backend=backend,
        background_tasks=background_tasks,
        document_ids=payload.document_ids,
        mode=payload.mode,
        answers=[a.model_dump() for a in payload.answers] if payload.answers else None,
    )
    return await _detail(db, conversation)
