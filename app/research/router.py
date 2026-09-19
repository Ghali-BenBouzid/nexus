import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.agents.schemas import ResearchResult
from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
from app.billing.service import ensure_budget
from app.db.session import get_db
from app.models.query import QueryStatus
from app.models.user import User
from app.research import repository, service
from app.research.dependencies import get_model, get_search_backend
from app.research.schemas import (
    QueryCreate,
    QueryDetail,
    QueryEventResponse,
    QueryResponse,
    ReviseRequest,
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
        error=query.error,
        stopped=repository.stopped_by_user(query),
        plan=query.plan,
        sources=result.sources if result else [],
        consulted_sources=consulted,
        gaps=result.gaps if result else [],
        created_at=query.created_at,
        completed_at=query.completed_at,
        # Computed here, not from a timestamp, so the client's clock never matters.
        seconds_since_heartbeat=_seconds_since(query.heartbeat_at),
    )


@router.post("/query/{query_id}/confirm", status_code=204)
async def confirm_plan(
    query_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Any, not BaseChatModel: it is a pydantic model, and FastAPI would read
    # the annotation as a request body rather than a dependency.
    model: Any = Depends(get_model),
    backend: SearchBackend = Depends(get_search_backend),
):
    """Approve the proposed plan and run the research (phase 2). Only valid while
    the query is awaiting_plan; same ownership 404 as the detail endpoint."""
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    if query.status != QueryStatus.awaiting_plan or not query.plan:
        raise HTTPException(status_code=409, detail="No plan is awaiting confirmation.")
    await ensure_budget(db, current_user)
    # Pending until a job takes it (then running, with a heartbeat). Anything but
    # awaiting_plan also turns a second confirm into a 409.
    await repository.set_status(db, query_id, QueryStatus.pending)
    await jobs.submit(
        background_tasks,
        service.review_plan_job,
        model=model,
        backend=backend,
        query_id=query_id,
        user_id=current_user.id,
        approved=True,
    )


@router.post("/query/{query_id}/revise", status_code=204)
async def revise_plan(
    query_id: int,
    payload: ReviseRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    # Any, not BaseChatModel: it is a pydantic model, and FastAPI would read
    # the annotation as a request body rather than a dependency.
    model: Any = Depends(get_model),
    backend: SearchBackend = Depends(get_search_backend),
):
    """Reject the plan (optionally with feedback) and re-plan. Loops back to
    awaiting_plan. Only valid while the query is awaiting_plan."""
    query = await repository.get_query(
        db=db, query_id=query_id, user_id=current_user.id
    )
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    if query.status != QueryStatus.awaiting_plan:
        raise HTTPException(status_code=409, detail="No plan is awaiting revision.")
    await ensure_budget(db, current_user)
    await repository.set_status(db, query_id, QueryStatus.pending)
    await jobs.submit(
        background_tasks,
        service.review_plan_job,
        model=model,
        backend=backend,
        query_id=query_id,
        user_id=current_user.id,
        approved=False,
        feedback=payload.feedback,
    )
