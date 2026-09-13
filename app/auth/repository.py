from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_user_by_id(db: AsyncSession, id: int) -> User | None:
    return await db.get(User, id)


async def get_user_by_invite_hash(db: AsyncSession, token_hash: str) -> User | None:
    result = await db.execute(select(User).where(User.invite_token_hash == token_hash))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


async def create_user(
    db: AsyncSession,
    *,
    name: str,
    email: str | None,
    invite_token_hash: str,
    budget_micro_usd: int,
    expires_at: datetime | None,
) -> User:
    user = User(
        name=name,
        email=email,
        invite_token_hash=invite_token_hash,
        budget_micro_usd=budget_micro_usd,
        expires_at=expires_at,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
