from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import AgentEvent, Report, ResearchResult
from app.models.conversation import Message
from app.models.query import Query, QueryEvent, QueryKind, QueryStatus

# A query some job may still act on. The writes that end a job only move a query
# still in flight, so two processes (the API stopping a run, a worker finishing
# it) can never overwrite each other's outcome.
_IN_FLIGHT = (QueryStatus.pending, QueryStatus.running)
STOPPED_RESPONDING = "The research stopped responding. Try again."
STOPPED = "Research was stopped."


# A run that answers a message of its own is that turn, and is read in the
# thread like any other answer. Outputs is for the runs with nowhere else to be:
# the ones the supervisor started on the side while it was answering something
# else. Listing a turn there too would show the same report in two places.
_HAS_NO_TURN = ~select(Message.id).where(Message.query_id == Query.id).exists()


def stopped_by_user(query: Query) -> bool:
    """A failed query the user stopped, as opposed to one that broke.
    ponytail: read from the stop's message; a "stopped" status if it needs more."""
    return query.status == QueryStatus.failed and query.error == STOPPED


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
            Query.kind != QueryKind.deep_research,
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


async def stalled_deep_runs(db: AsyncSession, stale_after_seconds: float) -> list[int]:
    """Deep runs whose worker stopped beating: redeployed, or crashed. They are
    the one kind that is checkpointed, so they are handed back to a worker
    instead of being failed like everything else. The heartbeat is bumped as they
    are handed over, so a second reaper pass does not queue them twice."""
    cutoff = _now() - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        update(Query)
        .where(
            Query.status == QueryStatus.running,
            Query.kind == QueryKind.deep_research,
            or_(Query.heartbeat_at.is_(None), Query.heartbeat_at < cutoff),
        )
        .values(heartbeat_at=_now())
        .returning(Query.id)
        .execution_options(synchronize_session=False)
    )
    ids = [row for row in result.scalars().all()]
    await db.commit()
    return ids


async def list_conversation_artifacts(
    db: AsyncSession, conversation_id: int
) -> list[Query]:
    """Every artifact run a conversation started, finished or not, newest first:
    what its Outputs panel shows, including the one still running."""
    result = await db.execute(
        select(Query)
        .where(
            Query.conversation_id == conversation_id,
            Query.kind != QueryKind.chat,
            _HAS_NO_TURN,
        )
        .order_by(Query.created_at.desc())
    )
    return list(result.scalars().all())


async def list_conversation_reports(
    db: AsyncSession, conversation_id: int
) -> list[Query]:
    """The finished reports a conversation has produced, oldest first: what the
    supervisor may read back with read_report."""
    result = await db.execute(
        select(Query)
        .where(
            Query.conversation_id == conversation_id,
            Query.kind != QueryKind.chat,
            Query.status == QueryStatus.complete,
        )
        .order_by(Query.created_at)
    )
    return list(result.scalars().all())


async def create_pending_query(
    db: AsyncSession,
    user_id: int,
    prompt: str,
    title: str | None = None,
    *,
    kind: QueryKind = QueryKind.chat,
    conversation_id: int | None = None,
) -> Query:
    query = Query(
        user_id=user_id,
        prompt=prompt,
        title=title,
        kind=kind,
        conversation_id=conversation_id,
        status=QueryStatus.pending,
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


async def list_artifacts(db: AsyncSession, user_id: int) -> list[Query]:
    """The runs that produced something the user keeps: deep research reports and
    fact checks, newest first. A chat turn is not one: its answer lives in the
    conversation."""
    result = await db.execute(
        select(Query)
        .where(Query.user_id == user_id, Query.kind != QueryKind.chat, _HAS_NO_TURN)
        .order_by(Query.created_at.desc())
    )
    return list(result.scalars().all())


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


async def complete_answer(
    db: AsyncSession,
    query_id: int,
    reply: str,
    *,
    result: ResearchResult | None = None,
) -> None:
    """End a chat turn with the supervisor's answer and the sources it cited."""
    await _transition(
        db,
        query_id,
        (QueryStatus.running,),
        status=QueryStatus.complete,
        reply=reply,
        result=result.model_dump() if result else None,
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
