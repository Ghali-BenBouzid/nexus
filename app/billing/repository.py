from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import LLMUsage


async def spent_micro_usd(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(LLMUsage.cost_micro_usd), 0)).where(
            LLMUsage.user_id == user_id
        )
    )
    return int(result.scalar_one())


async def spent_by_user(db: AsyncSession) -> dict[int, int]:
    result = await db.execute(
        select(LLMUsage.user_id, func.sum(LLMUsage.cost_micro_usd)).group_by(
            LLMUsage.user_id
        )
    )
    return {user_id: int(total) for user_id, total in result.all()}


async def add_usage(
    db: AsyncSession,
    *,
    user_id: int,
    query_id: int | None,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_micro_usd: int,
) -> None:
    db.add(
        LLMUsage(
            user_id=user_id,
            query_id=query_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micro_usd=cost_micro_usd,
        )
    )
    await db.commit()
