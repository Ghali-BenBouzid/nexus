from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.research import service
from app.research.schemas import QueryCreate, QueryResponse

router = APIRouter(prefix="/research")


@router.post("/query", status_code=201, response_model=QueryResponse)
async def create_query(
    query_create: QueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    created_query = await service.handle_query(
        db=db, user_id=current_user.id, prompt=query_create.prompt
    )

    return created_query
