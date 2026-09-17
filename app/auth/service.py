from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repository
from app.auth.security import create_access_token, hash_invite_token, new_invite_token
from app.billing.service import to_micro_usd
from app.core.config import settings
from app.models.user import User

INVALID_INVITE = "This invite link is not valid."
ACCESS_EXPIRED = "This demo access has expired. Ask for a new invite link."


def invite_url(token: str) -> str:
    return f"{settings.frontend_url.rstrip('/')}/invite/{token}"


def _expiry(days: int) -> datetime | None:
    # 0 days means the account never expires.
    return datetime.now(UTC) + timedelta(days=days) if days > 0 else None


async def create_demo_account(
    db: AsyncSession,
    *,
    name: str,
    email: str | None = None,
    budget_usd: float | None = None,
    days: int | None = None,
) -> tuple[User, str]:
    """Create an account and return it with its raw invite token (shown once)."""
    token, token_hash = new_invite_token()
    user = await repository.create_user(
        db,
        name=name,
        email=email,
        invite_token_hash=token_hash,
        budget_micro_usd=to_micro_usd(
            settings.default_budget_usd if budget_usd is None else budget_usd
        ),
        expires_at=_expiry(settings.default_access_days if days is None else days),
    )
    return user, token


async def update_account(
    db: AsyncSession,
    user: User,
    *,
    budget_usd: float | None = None,
    days: int | None = None,
    new_link: bool = False,
) -> str | None:
    """Top up, extend or re-link an account. Returns the new raw invite token when
    ``new_link`` is set (the old link stops working), else None."""
    token = None
    if budget_usd is not None:
        user.budget_micro_usd = to_micro_usd(budget_usd)
    if days is not None:
        user.expires_at = _expiry(days)
    if new_link:
        token, user.invite_token_hash = new_invite_token()
    await db.commit()
    return token


async def redeem_invite(db: AsyncSession, token: str) -> str:
    """Exchange an invite token for an access token."""
    user = await repository.get_user_by_invite_hash(db, hash_invite_token(token))
    if user is None:
        raise HTTPException(status_code=401, detail=INVALID_INVITE)
    if user.is_expired:
        raise HTTPException(status_code=403, detail=ACCESS_EXPIRED)
    return create_access_token(user.id)
