import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.agents.schemas import ResearchResult
from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
from app.billing.service import ensure_budget
from app.db.session import get_db
from app.models.query import Query, QueryStatus
from app.models.user import User
from app.research import bus, repository, service
from app.research.dependencies import get_model, get_search_backend
from app.research.schemas import (
    ArtifactSummary,
    QueryCreate,
    QueryDetail,
    QueryEventResponse,
    QueryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research")


def _seconds_since(moment: datetime | None) -> float | None:
    if moment is None:
        return None
    if moment.tzinfo is None:  # SQLite (the tests) drops the zone; it is UTC
        moment = moment.replace(tzinfo=UTC)
    return round((datetime.now(UTC) - moment).total_seconds(), 1)


def _load_result(raw: dict | None, query_id: int) -> ResearchResult | None:
    """Rehydrate the stored dump, tolerating a malformed/legacy blob: log and
    fall back to None rather than 500-ing the detail endpoint."""
    if not raw:
        return None
    try:
        return ResearchResult(**raw)
    except ValidationError:
        logger.warning("query %s has an unreadable result blob", query_id)
        return None


@router.post("/query", status_code=202, response_model=QueryResponse)
async def create_query(
    query_create: QueryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Any, not BaseChatModel: it is a pydantic model, and FastAPI would read
    # the annotation as a request body rather than a dependency.
    model: Any = Depends(get_model),
    backend: SearchBackend = Depends(get_search_backend),
):
    await ensure_budget(db, current_user)
    query = await repository.create_pending_query(
        db=db, user_id=current_user.id, prompt=query_create.prompt
    )
    # provider/backend have no request-scoped teardown, so an inline job can hold
    # them past the response; a worker builds its own.
    await jobs.submit(
        background_tasks,
        service.run_research_job,
        model=model,
        backend=backend,
        query_id=query.id,
        prompt=query.prompt,
        user_id=current_user.id,
    )
    return query


@router.get("/query", response_model=list[QueryResponse])
async def list_queries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await repository.list_queries(db=db, user_id=current_user.id)


@router.get("/artifacts", response_model=list[ArtifactSummary])
async def list_artifacts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every report this account has: deep research runs and fact checks, newest
    first. Declared before /query/{id} so "artifacts" is never read as an id."""
    return await repository.list_artifacts(db=db, user_id=current_user.id)


@router.get("/query/{query_id}/events", response_model=list[QueryEventResponse])
async def get_query_events(
    query_id: int,
    after: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tail the live agent feed: events for this query with id > ``after`` (the
    last id the client saw), oldest first. Same ownership guard as the detail
    endpoint — a non-owner gets 404 so the id's existence doesn't leak."""
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    return await repository.list_events(db=db, query_id=query_id, after_id=after)


@router.get("/query/{query_id}/stream")
async def stream_query_events(
    query_id: int,
    after: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The live agent feed as it happens, over server-sent events.

    The durable feed is drained first, from ``after``, so a browser that arrives
    late or reloads sees the run's stages before it starts following along. Only
    then does it join the bus, which carries the stages again plus the tokens
    that are never stored.

    Both halves matter: without the drain a reload shows an empty thread, and
    without the bus the reply appears all at once when the run ends.
    """
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    return StreamingResponse(
        feed(db, query, after=after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx (Railway, and any proxy in front of it) buffers a response
            # body by default, which holds every frame until the run ends.
            "X-Accel-Buffering": "no",
        },
    )


async def feed(db: AsyncSession, query: Query, *, after: int = 0) -> AsyncIterator[str]:
    """One query's feed as SSE frames: what was missed, then what happens next.

    Its own function rather than a closure so it can be driven directly. A test
    that goes through HTTP cannot produce events while the response is held
    open, which is the one behaviour worth proving here.
    """
    seen = after
    for stored in await repository.list_events(
        db=db, query_id=query.id, after_id=after
    ):
        seen = stored.id
        yield _frame(stored.type, stored.message, stored.data, stored.id)
    # A run that ended while nobody watched has nothing left to send.
    if query.status in (QueryStatus.complete, QueryStatus.failed):
        yield _frame(bus.DONE, "", None, seen)
        return
    async with bus.subscribe(query.id) as live:
        async for event in live:
            if event is None:
                # Both a keep-alive, because a proxy closes a quiet stream, and
                # the run's liveness: a job that died mid-tool sends nothing at
                # all, and this is what lets the bar say so.
                await db.refresh(query, ["heartbeat_at"])
                yield _frame(
                    "heartbeat", "", {"since": _seconds_since(query.heartbeat_at)}, None
                )
                continue
            yield _frame(event.type, event.message, event.data, None)
            if event.type == bus.DONE:
                return


def _frame(
    type_: str, message: str, data: dict[str, Any] | None, event_id: int | None
) -> str:
    """One SSE frame. ``id`` is the durable feed's cursor, present only on an
    event that was stored, so a reconnecting client can resume from it."""
    payload: dict[str, Any] = {"type": type_, "message": message, "data": data}
    if event_id is not None:
        payload["id"] = event_id
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/query/{query_id}/cancel", status_code=204)
async def cancel_query(
    query_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop a run the user halted. Requests cooperative cancellation of the job
    (so it stops spending quota) and marks the query failed. Same ownership 404 as
    the detail endpoint. A terminal query is left untouched (idempotent)."""
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    # The stop is the status itself: a job, in this process or on a worker, sees
    # it on its next heartbeat and stops spending. An awaiting_plan query has no
    # job and just resolves. One that already ended keeps its outcome.
    await repository.fail_query(db, query_id, repository.STOPPED)


@router.get("/query/{query_id}", response_model=QueryDetail)
async def get_query(
    query_id: int,
    include_provenance: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        # 404 (not 403) for another user's id so the id's existence doesn't leak.
        raise HTTPException(status_code=404, detail="Query not found")

    # Rehydrate the stored dump back into a ResearchResult (closes the
    # model_dump round-trip); null until the job completes.
    result = _load_result(query.result, query.id)
    # The full provenance trail is an opt-in extra (?include_provenance=true): it
    # is heavy and most callers only want the cited sources. When asked for, it is
    # the sources that were looked at but NOT cited, so it never duplicates the
    # cited list shown alongside it.
    consulted: list = []
    if result and include_provenance:
        cited_urls = {s.url for s in result.sources}
        consulted = [s for s in result.consulted_sources if s.url not in cited_urls]
    return QueryDetail(
        id=query.id,
        prompt=query.prompt,
        title=query.title,
        status=query.status,
        report=query.report,
        reply=query.reply,
        reply_parts=query.reply_parts,
        error=query.error,
        stopped=repository.stopped_by_user(query),
        kind=query.kind,
        sources=result.sources if result else [],
        consulted_sources=consulted,
        gaps=result.gaps if result else [],
        created_at=query.created_at,
        completed_at=query.completed_at,
        # Computed here, not from a timestamp, so the client's clock never matters.
        seconds_since_heartbeat=_seconds_since(query.heartbeat_at),
    )
