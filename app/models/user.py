from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    """A demo account. There is no public signup and no password: an admin creates
    the account (``python -m app.admin``) and hands out an invite link. The link's
    token is stored only as a hash. Each account has its own spending budget and
    an optional expiry date."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)  # who the invite is for
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    invite_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    # Integer micro-dollars (1e-6 USD), like the llm_usage ledger, so sums are exact.
    budget_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        # SQLite (the test suite) returns timezone-aware columns naive; they were
        # written in UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= datetime.now(UTC)
