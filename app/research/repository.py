from sqlalchemy.ext.asyncio import AsyncSession

from app.models.query import Query


async def create_query(
    db: AsyncSession, user_id: int, prompt: str, report: str | None
) -> Query:
    query = Query(user_id=user_id, prompt=prompt, report=report)

    db.add(query)
    await db.commit()
    await db.refresh(query)

    return query
