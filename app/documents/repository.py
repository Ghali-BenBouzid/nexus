from sqlalchemy import func, select
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


async def remove(db: AsyncSession, document: Document) -> None:
    await db.delete(document)
    await db.commit()
