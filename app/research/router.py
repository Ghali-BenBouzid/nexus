import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.provider import LLMProvider
from app.agents.schemas import ResearchResult
from app.agents.tools import SearchBackend
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.research import repository, service
from app.research.dependencies import get_provider, get_search_backend
from app.research.schemas import QueryCreate, QueryDetail, QueryResponse

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


@router.get("/query/{query_id}", response_model=QueryDetail)
async def get_query(
    query_id: int,
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
    return QueryDetail(
        id=query.id,
        prompt=query.prompt,
        status=query.status,
        report=query.report,
        error=query.error,
        sources=result.sources if result else [],
        consulted_sources=result.consulted_sources if result else [],
        gaps=result.gaps if result else [],
        created_at=query.created_at,
        completed_at=query.completed_at,
    )
