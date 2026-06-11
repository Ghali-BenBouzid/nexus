from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import Report, ResearchResult
from app.models.query import Query, QueryStatus


async def reap_interrupted_queries(db: AsyncSession) -> int:
    """Fail any query still 'running' from a previous process. Jobs run in-process,
    so a query left running after a restart (e.g. a deploy) is orphaned: nothing is
    left to finish or time it out. Returns how many were reaped."""
    result = await db.execute(
        update(Query)
        .where(Query.status == QueryStatus.running)
        .values(
            status=QueryStatus.failed,
            error="Interrupted by a server restart.",
            completed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return result.rowcount or 0


async def create_pending_query(db: AsyncSession, user_id: int, prompt: str) -> Query:
    query = Query(user_id=user_id, prompt=prompt, status=QueryStatus.pending)
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


async def get_query(db: AsyncSession, query_id: int, user_id: int) -> Query | None:
    result = await db.execute(
        select(Query).where(Query.id == query_id, Query.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_queries(db: AsyncSession, user_id: int) -> list[Query]:
    result = await db.execute(
        select(Query).where(Query.user_id == user_id).order_by(Query.created_at.desc())
    )
    return list(result.scalars().all())


async def set_status(db: AsyncSession, query_id: int, status: QueryStatus) -> None:
    query = await db.get(Query, query_id)
    if query is None:
        return
    query.status = status
    await db.commit()


async def complete_query(
    db: AsyncSession,
    query_id: int,
    report: Report,
    result: ResearchResult,
) -> None:
    query = await db.get(Query, query_id)
    if query is None:
        return
    query.status = QueryStatus.complete
    # report column = rendered prose; result JSONB = the structured, style-agnostic
    # ResearchResult (points + per-point citations) so it can be re-rendered later.
    query.report = report.content
    query.result = result.model_dump()
    query.completed_at = datetime.now(UTC)
    await db.commit()


async def fail_query(db: AsyncSession, query_id: int, error: str) -> None:
    query = await db.get(Query, query_id)
    if query is None:
        return
    query.status = QueryStatus.failed
    query.error = error
    query.completed_at = datetime.now(UTC)
    await db.commit()
