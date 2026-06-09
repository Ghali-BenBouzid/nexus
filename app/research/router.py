from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.provider import LLMProvider
from app.agents.search import TavilyBackend
from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.research import repository, service
from app.research.dependencies import get_provider, get_search_backend
from app.research.schemas import QueryCreate, QueryDetail, QueryResponse

router = APIRouter(prefix="/research")


@router.post("/query", status_code=202, response_model=QueryResponse)
async def create_query(
    query_create: QueryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
    backend: TavilyBackend = Depends(get_search_backend),
):
    query = await repository.create_pending_query(
        db=db, user_id=current_user.id, prompt=query_create.prompt
    )
    # provider/backend are passed by value (they outlive the response, unlike db);
    # the job opens and closes them itself.
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

    result = query.result or {}
    return QueryDetail(
        id=query.id,
        prompt=query.prompt,
        status=query.status,
        report=query.report,
        error=query.error,
        sources=result.get("sources", []),
        gaps=result.get("failed_subquestions", []),
        created_at=query.created_at,
        completed_at=query.completed_at,
    )
