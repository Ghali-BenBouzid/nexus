import logging

from app.agents.provider import LLMProvider, LLMResponse, Message, Usage
from app.agents.tools import ToolSpec
from app.billing import repository
from app.billing.service import to_micro_usd
from app.db import session as db_session

logger = logging.getLogger(__name__)


class MeteredProvider:
    """Wraps an LLMProvider and bills each call to a demo account: after every
    ``generate`` it writes the call's tokens and cost (as the provider reports
    them, e.g. OpenRouter's ``usage.cost``) to the llm_usage ledger.

    Same decorator shape as CachingSearchBackend, so the agents never know
    billing exists. Each row is written in its own short-lived session, like the
    event sink, because researchers call the model concurrently."""

    def __init__(
        self, inner: LLMProvider, *, user_id: int, query_id: int | None = None
    ) -> None:
        self.inner = inner
        self.user_id = user_id
        self.query_id = query_id

    async def __aenter__(self) -> "MeteredProvider":
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.inner.__aexit__(exc_type, exc, tb)

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        response = await self.inner.generate(messages, tools, tool_choice)
        if response.usage is not None:
            await self._record(response.usage)
        return response

    async def _record(self, usage: Usage) -> None:
        # ponytail: best-effort, like the event feed. A lost row under-bills one
        # call; the key's credit limit still caps the real spend.
        try:
            async with db_session.SessionLocal() as db:
                await repository.add_usage(
                    db,
                    user_id=self.user_id,
                    query_id=self.query_id,
                    model=getattr(self.inner, "model", "unknown"),
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_micro_usd=to_micro_usd(usage.cost_usd or 0.0),
                )
        except Exception:
            logger.exception("failed to record LLM usage for user %s", self.user_id)
