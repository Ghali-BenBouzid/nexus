"""The loop every agent runs.

An agent is a prompt, a set of tools and this loop. It sees the conversation,
calls a tool, sees the result, and decides again, until it reaches a tool the
caller has to handle itself (sending researchers, answering) or runs out of
budget. Nothing about the order is written here: which tool, how many times, and
when to stop are the model's to judge, which is the point.

Two kinds of tool:

- **Executable**: the loop runs it and feeds the result back (read a document,
  one search, read a page). The agent never leaves this module for those.
- **Control**: the loop stops and hands the call to the caller, because it needs
  something this module has no business doing (fanning out researchers on the
  graph, ending the turn, calling another agent).

What is enforced here, and nowhere else: the step budget, the deadline, the
cooperative stop, and that a malformed or missing tool call is fed back rather
than crashing a turn. An agent that never stops is this design's failure mode.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent, Source
from app.agents.tools import RetrievalResult, Tool, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]
ShouldCancel = Callable[[], bool]


class StoppedError(Exception):
    """The user stopped the run while the agent was working."""


@dataclass
class Sources:
    """The turn's citation registry: every source any tool returned, numbered in
    the order it arrived. The numbers are the only ones an agent may cite, and a
    marker pointing outside this list is stripped before the user sees the text.

    Deduped by url, so the same page found twice keeps one number.
    """

    items: list[Source] = field(default_factory=list)
    _by_url: dict[str, int] = field(default_factory=dict)

    def register(self, sources: list[Source]) -> list[int]:
        """Add sources and return their numbers, 1-based, in the order given."""
        numbers = []
        for source in sources:
            number = self._by_url.get(source.url)
            if number is None:
                self.items.append(source)
                number = len(self.items)
                self._by_url[source.url] = number
            numbers.append(number)
        return numbers

    def legend(self, numbers: list[int]) -> str:
        """The "cite these by number" block appended to a tool result."""
        lines = [
            f"[{n}] {self.items[n - 1].title} ({self.items[n - 1].url})"
            for n in dict.fromkeys(numbers)  # unique, order kept
        ]
        return "\n\nCite these sources by number:\n" + "\n".join(lines) if lines else ""


@dataclass
class Call:
    """A control tool the agent asked for, handed back to the caller."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Budget:
    """What bounds one agent's turn. Steps are model calls; the deadline is wall
    clock, shared with everything the turn already spent."""

    max_steps: int
    deadline: float | None = None  # time.monotonic() instant

    def exhausted(self, steps: int) -> bool:
        out_of_time = self.deadline is not None and time.monotonic() >= self.deadline
        return steps >= self.max_steps or out_of_time


async def _noop(event: AgentEvent) -> None:
    return None


async def run(
    messages: list[Message],
    *,
    provider: LLMProvider,
    specs: list[ToolSpec],
    executables: dict[str, Tool],
    control: set[str],
    sources: Sources,
    budget: Budget,
    agent: str = "agent",
    emit: Emit = _noop,
    should_cancel: ShouldCancel = lambda: False,
) -> Call | None:
    """Run the agent until it calls a control tool, or its budget runs out.

    ``messages`` is extended in place with everything the agent said and saw, so
    the caller can answer a control call and run again from where it stopped.
    Returns the control call, or None when the budget ran out first: the caller
    decides what an unfinished turn means.
    """
    steps = 0
    while not budget.exhausted(steps):
        if should_cancel():
            raise StoppedError(f"{agent} was stopped")
        steps += 1
        response = await provider.generate(messages, tools=specs, tool_choice="auto")
        messages.append(_assistant(response))

        if not response.tool_calls:
            # A plain reply when a tool was expected: say so and let it retry.
            messages.append(
                Message(role="user", content="Use one of your tools to continue.")
            )
            continue

        for call in response.tool_calls:
            if call.name in control:
                return Call(id=call.id, name=call.name, args=call.args)
            result = await _execute(call.name, call.args, executables, agent, emit)
            messages.append(
                Message(
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content=_register(result, sources),
                )
            )

    await emit(
        AgentEvent(
            type="budget_spent",
            message=f"{agent} reached its limit",
            data={"agent": agent, "steps": steps},
        )
    )
    return None


async def _execute(
    name: str,
    args: dict[str, Any],
    executables: dict[str, Tool],
    agent: str,
    emit: Emit,
) -> ToolResult:
    tool = executables.get(name)
    if tool is None:
        # A hallucinated tool name: tell it what happened, do not end the turn.
        return ToolResult(content=f"There is no tool called {name}.")
    await emit(
        AgentEvent(
            type="tool_call",
            message=f"{name}({args})",
            data={"agent": agent, "tool": name, "args": args},
        )
    )
    try:
        return await tool.execute(**args)
    except ValidationError as exc:
        return ToolResult(content=f"{name} was called with invalid arguments: {exc}")
    except Exception as exc:  # noqa: BLE001 -- one failed tool is not a failed turn
        logger.warning("%s failed in %s", name, agent, exc_info=exc)
        await emit(
            AgentEvent(
                type="tool_error",
                message=f"{name} failed: {exc}",
                data={"agent": agent, "tool": name},
            )
        )
        return ToolResult(content=f"{name} failed: {exc}")


def _register(result: ToolResult, sources: Sources) -> str:
    """Register whatever the tool retrieved and append its numbers, so the agent
    can only ever cite something that was really read."""
    if not isinstance(result, RetrievalResult) or not result.sources:
        return result.content
    numbers = sources.register(result.sources)
    return result.content + sources.legend(numbers)


def _assistant(response: LLMResponse) -> Message:
    return Message(
        role="assistant", content=response.text, tool_calls=response.tool_calls
    )
