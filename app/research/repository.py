from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import AgentEvent, Report, ResearchResult
from app.models.query import Query, QueryEvent, QueryStatus

# A query some job may still act on. The writes that end a job only move a query
# still in flight, so two processes (the API stopping a run, a worker finishing
# it) can never overwrite each other's outcome.
_IN_FLIGHT = (QueryStatus.pending, QueryStatus.running, QueryStatus.awaiting_plan)
STOPPED_RESPONDING = "The research stopped responding. Try again."


def _now() -> datetime:
    return datetime.now(UTC)


async def reap_interrupted_queries(db: AsyncSession) -> int:
    """Fail any query still 'running' from a previous process. With inline jobs
    (JOB_QUEUE=inline) they run in the API process, so a query left running after
    a restart is orphaned: nothing is left to finish or time it out. Returns how
    many were reaped."""
    result = await db.execute(
        update(Query)
        .where(Query.status == QueryStatus.running)
        .values(
            status=QueryStatus.failed,
            error="Interrupted by a server restart.",
            completed_at=_now(),
        )
    )
    await db.commit()
    return result.rowcount or 0


async def reap_stalled_queries(db: AsyncSession, stale_after_seconds: float) -> int:
    """Fail running queries whose job stopped beating: its worker died or was
    redeployed mid-run. Safe with several workers, since a live job keeps beating.
    Returns how many were reaped."""
    cutoff = _now() - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        update(Query)
        .where(
            Query.status == QueryStatus.running,
            or_(Query.heartbeat_at.is_(None), Query.heartbeat_at < cutoff),
        )
        .values(
            status=QueryStatus.failed,
            error=STOPPED_RESPONDING,
            completed_at=_now(),
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0


async def create_pending_query(
    db: AsyncSession, user_id: int, prompt: str, title: str | None = None
) -> Query:
    query = Query(
        user_id=user_id, prompt=prompt, title=title, status=QueryStatus.pending
    )
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


async def _transition(db: AsyncSession, query_id: int, allowed, **values) -> bool:
    """Update the query only if its status is one of ``allowed``, atomically."""
    result = await db.execute(
        update(Query)
        .where(Query.id == query_id, Query.status.in_(allowed))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return bool(result.rowcount)


async def mark_running(db: AsyncSession, query_id: int) -> bool:
    """A job takes its query: pending (or running, when one job hands the turn
    to the next) becomes running, with a fresh heartbeat. False when the user
    stopped it while it waited in the queue, so the job has nothing to do."""
    return await _transition(
        db,
        query_id,
        (QueryStatus.pending, QueryStatus.running),
        status=QueryStatus.running,
        heartbeat_at=_now(),
    )


async def touch_heartbeat(db: AsyncSession, query_id: int) -> QueryStatus | None:
    """Mark the query's job as alive now, and return the query's status: a stop
    from the user shows up here as failed, wherever the stop was made."""
    result = await db.execute(
        update(Query)
        .where(Query.id == query_id)
        .values(heartbeat_at=_now())
        .returning(Query.status)
        .execution_options(synchronize_session=False)
    )
    status = result.scalar_one_or_none()
    await db.commit()
    return status


async def update_turn(
    db: AsyncSession, query_id: int, *, prompt: str, title: str | None
) -> None:
    """Record what the supervisor made of the message: the self-contained research
    query (or the compose instructions) and the report's title."""
    await db.execute(
        update(Query)
        .where(Query.id == query_id)
        .values(prompt=prompt, title=title)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def set_plan(db: AsyncSession, query_id: int, plan: list[str]) -> None:
    """Store a proposed plan and pause for confirmation (human-in-the-loop). Only
    a running query moves, so a stop that landed while planning wins."""
    await _transition(
        db,
        query_id,
        (QueryStatus.running,),
        plan=plan,
        status=QueryStatus.awaiting_plan,
    )


async def complete_query(
    db: AsyncSession,
    query_id: int,
    report: Report,
    result: ResearchResult,
) -> None:
    """Save the finished report. Only a running query completes, so a stop that
    landed during the final write keeps the run stopped."""
    # report column = rendered prose; result JSONB = the structured, style-agnostic
    # ResearchResult (points + per-point citations) so it can be re-rendered later.
    await _transition(
        db,
        query_id,
        (QueryStatus.running,),
        status=QueryStatus.complete,
        report=report.content,
        result=result.model_dump(),
        completed_at=_now(),
    )


async def complete_answer(db: AsyncSession, query_id: int, reply: str) -> None:
    """End a turn the supervisor answered directly, with no research."""
    await _transition(
        db,
        query_id,
        (QueryStatus.running,),
        status=QueryStatus.complete,
        reply=reply,
        completed_at=_now(),
    )


async def add_event(db: AsyncSession, query_id: int, event: AgentEvent) -> None:
    """Append one agent event for a query. Called from the emit sink in its own
    short-lived session so concurrent emits never share a session."""
    db.add(
        QueryEvent(
            query_id=query_id,
            type=event.type,
            message=event.message,
            data=event.data,
        )
    )
    await db.commit()


async def list_events(
    db: AsyncSession, query_id: int, after_id: int
) -> list[QueryEvent]:
    """Events for a query with id greater than ``after_id``, in order. The id is a
    monotonic cursor, so a client tails the feed by passing the last id it saw."""
    result = await db.execute(
        select(QueryEvent)
        .where(QueryEvent.query_id == query_id, QueryEvent.id > after_id)
        .order_by(QueryEvent.id)
    )
    return list(result.scalars().all())


async def fail_query(db: AsyncSession, query_id: int, error: str) -> None:
    """Resolve an in-flight query as failed. One that already ended keeps its
    outcome, so a job winding down never overwrites the user's stop."""
    await _transition(
        db,
        query_id,
        _IN_FLIGHT,
        status=QueryStatus.failed,
        error=error,
        completed_at=_now(),
    )
