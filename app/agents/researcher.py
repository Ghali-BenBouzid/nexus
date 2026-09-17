import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from app.agents.language import detect_language
from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent, Finding, FindingClaim, Source
from app.agents.tools import (
    RetrievalResult,
    SubmitFinding,
    SubmitFindingArgs,
    Tool,
    ToolResult,
)
from app.observability import traced_step
from app.prompts import render
from app.prompts.researcher import PROMPT

Emit = Callable[[AgentEvent], Awaitable[None]]


async def _noop(event: AgentEvent) -> None:
    return None


def _never_cancel() -> bool:
    return False


@traced_step("research")
async def research(
    sub_question: str,
    *,
    provider: LLMProvider,
    tools: list[Tool],
    emit: Emit = _noop,
    should_cancel: Callable[[], bool] = _never_cancel,
    max_iters: int,
    deadline: float | None = None,
) -> Finding:
    """Run the ReAct tool-use loop for one sub-question and return a Finding.

    The model is given the executable ``tools`` plus the ``submit_finding``
    control tool; it searches/reads until it calls ``submit_finding`` (the
    terminal step), or the iteration cap or the ``deadline`` (a
    ``time.monotonic()`` instant) forces a final answer from what it has read.
    """
    submit = SubmitFinding()
    specs = [*tools, submit]
    executables = {tool.name: tool for tool in tools}
    consulted: list[Source] = []
    messages = render(
        PROMPT,
        sub_question=sub_question,
        language=detect_language(sub_question) or "",
    )

    # The researcher_start/done lifecycle is emitted by the orchestrator, which
    # knows this researcher's index and the total. The leaf emits only its own
    # internal steps (tool calls, errors, forced finish).
    out_of_time = False
    for _ in range(max_iters):
        # Cooperative cancel: bail before the next (expensive) model/tool round so a
        # stopped run stops spending quota. The empty finding becomes a gap, and the
        # orchestrator surfaces the cancellation after the fan-out.
        if should_cancel():
            return Finding(
                sub_question=sub_question,
                claims=[],
                consulted_sources=consulted,
                found_info=False,
            )
        # Out of time: stop searching and submit what was read so far (below),
        # rather than start a round that would push the whole run past its budget.
        if deadline is not None and time.monotonic() >= deadline:
            out_of_time = True
            break
        response = await provider.generate(messages, tools=specs, tool_choice="auto")
        messages.append(_assistant_message(response))

        if not response.tool_calls:
            messages.append(
                Message(
                    role="user",
                    content="Call a tool, or submit_finding when you are done.",
                )
            )
            continue

        for call in response.tool_calls:
            if call.name == submit.name:
                try:
                    return _build_finding(sub_question, call.args, consulted)
                except ValidationError as exc:
                    # Malformed final call: feed the error back (like a tool error)
                    # so the model can fix it while iterations remain, instead of
                    # hard-failing a researcher that already did the work.
                    await emit(
                        AgentEvent(
                            type="submit_invalid",
                            message=f"submit_finding was malformed: {exc}",
                        )
                    )
                    messages.append(
                        Message(
                            role="tool",
                            tool_call_id=call.id,
                            name=call.name,
                            content=(
                                f"submit_finding arguments were invalid: {exc}. "
                                "Call submit_finding again with valid arguments."
                            ),
                        )
                    )
                    continue

            result = await _run_tool(call.name, call.args, executables, emit)
            messages.append(
                Message(
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content=_register_and_format(result, consulted),
                )
            )

    # Iteration cap or deadline hit: force one final submit_finding (found_info is
    # the escape hatch so the model can honestly say it found nothing instead of
    # confabulating).
    reason = "Time budget reached" if out_of_time else "Max iterations reached"
    await emit(AgentEvent(type="researcher_forced", message=reason))
    response = await provider.generate(
        messages, tools=[submit], tool_choice=submit.name
    )
    if response.tool_calls:
        try:
            return _build_finding(sub_question, response.tool_calls[0].args, consulted)
        except ValidationError:
            pass
    return Finding(
        sub_question=sub_question,
        claims=[],
        consulted_sources=consulted,
        found_info=False,
    )


def _assistant_message(response: LLMResponse) -> Message:
    return Message(
        role="assistant",
        content=response.text,
        tool_calls=response.tool_calls,
    )


async def _run_tool(
    name: str,
    args: dict[str, Any],
    executables: dict[str, Tool],
    emit: Emit,
) -> ToolResult:
    tool = executables.get(name)
    if tool is None:
        return ToolResult(content=f"Unknown tool: {name}")
    await emit(
        AgentEvent(
            type="tool_call",
            message=f"{name}({args})",
            data={"tool": name, "args": args},
        )
    )
    try:
        return await tool.execute(**args)
    except Exception as exc:  # one failed tool call must not kill the whole loop
        await emit(AgentEvent(type="tool_error", message=f"{name} failed: {exc}"))
        return ToolResult(content=f"Tool {name} failed: {exc}")


def _register_and_format(result: ToolResult, consulted: list[Source]) -> str:
    """Register a tool result's sources into the running consulted list, assigning
    each a stable id (its index), and append a legend so the model can cite by id."""
    if not isinstance(result, RetrievalResult) or not result.sources:
        return result.content
    lines = []
    for source in result.sources:
        source_id = len(consulted)
        consulted.append(source)
        lines.append(f"[{source_id}] {source.title} ({source.url})")
    legend = "\n".join(lines)
    return f"{result.content}\n\nCite these sources by id:\n{legend}"


def _build_finding(
    sub_question: str,
    args: dict[str, Any],
    consulted: list[Source],
) -> Finding:
    parsed = SubmitFindingArgs(**args)
    claims = [
        FindingClaim(
            text=claim.text,
            sources=[
                consulted[i] for i in claim.cited_source_ids if 0 <= i < len(consulted)
            ],
        )
        for claim in parsed.claims
    ]
    return Finding(
        sub_question=sub_question,
        claims=claims,
        consulted_sources=consulted,
        found_info=parsed.found_info,
    )
