import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.provider import LLMProvider
from app.agents.schemas import ResearchResult
from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.query import QueryStatus
from app.models.user import User
from app.research import repository, service
from app.research.dependencies import get_provider, get_search_backend
from app.research.schemas import (
    QueryCreate,
    QueryDetail,
    QueryEventResponse,
    QueryResponse,
    ReviseRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research")


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
    provider: LLMProvider = Depends(get_provider),
    backend: SearchBackend = Depends(get_search_backend),
):
    if await service.over_daily_cap(db, current_user.id):
        raise HTTPException(
            status_code=429,
            detail="Daily research limit reached. Please try again tomorrow.",
        )
    query = await repository.create_pending_query(
        db=db, user_id=current_user.id, prompt=query_create.prompt
    )
    # provider/backend have no request-scoped teardown, so the task can hold them
    # past the response
    background_tasks.add_task(
        service.run_research_job,
        query.id,
        query.prompt,
        provider=provider,
        backend=backend,
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
    if query.status in (QueryStatus.pending, QueryStatus.running):
        service.request_cancel(query_id)
        await repository.fail_query(db, query_id, "Research was stopped.")
    elif query.status == QueryStatus.awaiting_plan:
        # Paused for plan confirmation: the plan job has already finished, so there
        # is no running job to signal. Just resolve the status, otherwise a reload
        # would rehydrate the query as still awaiting confirmation.
        await repository.fail_query(db, query_id, "Research was stopped.")


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
        error=query.error,
        plan=query.plan,
        sources=result.sources if result else [],
        consulted_sources=consulted,
        gaps=result.gaps if result else [],
        created_at=query.created_at,
        completed_at=query.completed_at,
    )


@router.post("/query/{query_id}/confirm", status_code=204)
async def confirm_plan(
    query_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
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
    await repository.set_status(db, query_id, QueryStatus.running)
    background_tasks.add_task(
        service.run_research_from_plan_job,
        query_id,
        query.plan,
        provider=provider,
        backend=backend,
    )


@router.post("/query/{query_id}/revise", status_code=204)
async def revise_plan(
    query_id: int,
    payload: ReviseRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
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
    await repository.set_status(db, query_id, QueryStatus.running)
    background_tasks.add_task(
        service.run_plan_job,
        query_id,
        query.prompt,
        provider=provider,
        feedback=payload.feedback,
    )
