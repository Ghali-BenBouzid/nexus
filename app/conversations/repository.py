from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageRole
from app.models.query import Query


async def create_conversation(
    db: AsyncSession, user_id: int, title: str | None = None
) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversation(
    db: AsyncSession, conversation_id: int, user_id: int
) -> Conversation | None:
    """User-scoped: a non-owner gets None (the router turns it into a 404)."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_conversations(db: AsyncSession, user_id: int) -> list[Conversation]:
    """The caller's conversations, most-recently-active first."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list(result.scalars().all())


async def add_message(
    db: AsyncSession,
    conversation_id: int,
    role: MessageRole,
    content: str = "",
    query_id: int | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        query_id=query_id,
    )
    db.add(message)
    # Adding a message makes the conversation the most recently active one.
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(UTC))
    )
    await db.commit()
    await db.refresh(message)
    return message


async def set_title(db: AsyncSession, conversation_id: int, title: str) -> None:
    """Name the conversation (once), so the sidebar shows a real title instead of
    the fallback. Called with the first report's supervisor-given title."""
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return
    conversation.title = title
    await db.commit()


async def list_messages(db: AsyncSession, conversation_id: int) -> list[Message]:
    """Messages in order (id is monotonic)."""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    )
    return list(result.scalars().all())


async def queries_by_id(db: AsyncSession, ids: list[int]) -> dict[int, Query]:
    """Batch-load the queries a thread's assistant messages point at, so the
    detail view renders reports without an N+1 of per-message reads."""
    if not ids:
        return {}
    result = await db.execute(select(Query).where(Query.id.in_(ids)))
    return {query.id: query for query in result.scalars().all()}
