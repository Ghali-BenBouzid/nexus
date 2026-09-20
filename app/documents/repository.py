from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


async def add(db: AsyncSession, document: Document) -> Document:
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def list_for_conversation(
    db: AsyncSession, conversation_id: int
) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.conversation_id == conversation_id)
        .order_by(Document.id)
    )
    return list(result.scalars())


async def count_for_conversation(db: AsyncSession, conversation_id: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Document)
        .where(Document.conversation_id == conversation_id)
    )
    return int(result.scalar_one())


async def get_for_user(
    db: AsyncSession, document_id: int, user_id: int
) -> Document | None:
    """User-scoped: someone else's document reads as missing."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def attach_to_message(
    db: AsyncSession, document_ids: list[int], *, message_id: int, user_id: int
) -> None:
    """Tie the files that were sent with a message to that message. Scoped to the
    owner, so an id someone else's file happens to have does nothing."""
    if not document_ids:
        return
    await db.execute(
        update(Document)
        .where(Document.id.in_(document_ids), Document.user_id == user_id)
        .values(message_id=message_id)
    )
    await db.commit()


async def remove(db: AsyncSession, document: Document) -> None:
    await db.delete(document)
    await db.commit()
