from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.dependencies import get_current_user
from app.auth.schemas import Account, InviteRedeem, Token
from app.billing import repository as billing_repository
from app.billing.service import to_usd
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/auth")


# No rate limit needed: an invite token is 256 random bits, so guessing one is
# not a realistic attack, and there is no signup left to abuse.
@router.post("/invite", response_model=Token)
async def redeem_invite(payload: InviteRedeem, db: AsyncSession = Depends(get_db)):
    return Token(access_token=await service.redeem_invite(db, payload.token))


@router.get("/me", response_model=Account)
async def me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    spent = await billing_repository.spent_micro_usd(db, current_user.id)
    return Account(
        id=current_user.id,
        name=current_user.name,
        expires_at=current_user.expires_at,
        budget_usd=to_usd(current_user.budget_micro_usd),
        spent_usd=to_usd(spent),
        remaining_usd=to_usd(max(0, current_user.budget_micro_usd - spent)),
    )
