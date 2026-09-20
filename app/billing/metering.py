"""Billing every model call to a demo account.

Each call's tokens and cost, as the provider reports them (OpenRouter puts
``cost`` in its ``usage`` block), are written to the ``llm_usage`` ledger, which
is what an account's budget is spent from. This module only knows how to write a
row; the agents never see billing at all, because ``app.agents.model.Billing``
carries it as middleware around every call.

Each row is written in its own short-lived session, like the event sink, because
researchers call the model concurrently.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.model import Usage
from app.billing import repository
from app.billing.service import to_micro_usd
from app.db import session as db_session

logger = logging.getLogger(__name__)

Record = Callable[[dict[str, Any]], Awaitable[None]]


def billing(*, user_id: int, query_id: int | None = None) -> Usage:
    """The callback that bills this account for every model call in a run."""
    return Usage(record=recorder(user_id=user_id, query_id=query_id))


def recorder(*, user_id: int, query_id: int | None = None) -> Record:
    async def record(usage: dict[str, Any]) -> None:
        # ponytail: best-effort, like the event feed. A lost row under-bills one
        # call; the key's credit limit still caps the real spend.
        try:
            async with db_session.SessionLocal() as db:
                await repository.add_usage(
                    db,
                    user_id=user_id,
                    query_id=query_id,
                    model=usage.get("model") or "unknown",
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cost_micro_usd=to_micro_usd(usage.get("cost_usd") or 0.0),
                )
        except Exception:
            logger.exception("failed to record LLM usage for user %s", user_id)

    return record
