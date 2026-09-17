from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LLMUsage(Base):
    """One billed model call. This append-only ledger is what an account's budget
    is checked against, and it records which run (query) spent the money, so the
    cost of a report can be measured. Cost is stored in integer micro-dollars
    (1e-6 USD) so sums are exact."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null for calls made outside a run (the supervisor routing a message).
    query_id: Mapped[int | None] = mapped_column(
        ForeignKey("queries.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
