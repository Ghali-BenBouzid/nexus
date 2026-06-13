from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.provider import LLMProvider
from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
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
from app.models.conversation import Conversation, Message
from app.models.query import Query
from app.models.user import User
from app.research.dependencies import get_provider, get_search_backend
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
        error=query.error,
        plan=query.plan,
        sources=result.sources if result else [],
        gaps=result.gaps if result else [],
    )


def _to_responses(
    messages: list[Message], queries: dict[int, Query]
) -> list[MessageResponse]:
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            query_id=m.query_id,
            created_at=m.created_at,
            query=_message_query(queries.get(m.query_id)) if m.query_id else None,
        )
        for m in messages
    ]


async def _detail(db: AsyncSession, conversation: Conversation) -> ConversationDetail:
    messages = await repository.list_messages(db, conversation.id)
    query_ids = [m.query_id for m in messages if m.query_id is not None]
    queries = await repository.queries_by_id(db, query_ids)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=_to_responses(messages, queries),
    )


@router.post("", response_model=ConversationDetail, status_code=201)
async def create(
    payload: ConversationCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
    backend: SearchBackend = Depends(get_search_backend),
):
    conversation = await repository.create_conversation(db, current_user.id)
    await service.submit_message(
        db,
        conversation,
        payload.prompt,
        provider=provider,
        backend=backend,
        background_tasks=background_tasks,
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
    conversation_id: int,
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
    conversation_id: int,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
    backend: SearchBackend = Depends(get_search_backend),
):
    conversation = await repository.get_conversation(
        db, conversation_id, current_user.id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await service.submit_message(
        db,
        conversation,
        payload.content,
        provider=provider,
        backend=backend,
        background_tasks=background_tasks,
    )
    return await _detail(db, conversation)
