"""Tell the live feed when an agent is waiting on the model.

A reasoning model can think for a minute before it replies. Without a sign, the
user cannot tell a model that is thinking from a run that is stuck, so every model
call is announced as a ``thinking`` event, which the UI shows with a running timer.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent
from app.agents.tools import ToolSpec

Emit = Callable[[AgentEvent], Awaitable[None]]


class ThinkingProvider:
    """Wraps a provider for one agent and emits ``thinking`` before each call.
    ``data`` rides along on the event (a researcher's index and total). The inner
    provider is opened by the job, so entering this one does nothing."""

    def __init__(self, inner: LLMProvider, emit: Emit, *, agent: str, **data: Any):
        self.inner = inner
        self.emit = emit
        self.agent = agent
        self.data = data

    async def __aenter__(self) -> "ThinkingProvider":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        await self.emit(
            AgentEvent(
                type="thinking",
                message=f"{self.agent.capitalize()} is thinking",
                data={"agent": self.agent, **self.data},
            )
        )
        return await self.inner.generate(messages, tools, tool_choice)
