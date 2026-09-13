from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import repository
from app.models.user import User

BUDGET_EXHAUSTED = (
    "This demo account has used up its budget. Ask for a top-up to keep researching."
)

_MICRO = 1_000_000


def to_micro_usd(usd: float) -> int:
    return round(usd * _MICRO)


def to_usd(micro_usd: int) -> float:
    return micro_usd / _MICRO


async def ensure_budget(db: AsyncSession, user: User) -> None:
    """Refuse new work (402) once an account has spent its budget.

    ponytail: checked when work starts, not before every model call, so a run
    already in flight finishes and can overshoot by its own cost (a few cents).
    The OpenRouter key's credit limit is the hard ceiling on the total bill.
    """
    if await repository.spent_micro_usd(db, user.id) >= user.budget_micro_usd:
        raise HTTPException(status_code=402, detail=BUDGET_EXHAUSTED)
