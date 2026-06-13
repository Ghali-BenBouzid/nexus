from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent, Finding, FindingClaim, Source
from app.agents.tools import (
    RetrievalResult,
    SubmitFinding,
    SubmitFindingArgs,
    Tool,
    ToolResult,
)

Emit = Callable[[AgentEvent], Awaitable[None]]

_SYSTEM_PROMPT = (
    "You are a research agent answering a single sub-question.\n"
    "- Use web_search to find sources, and fetch_page to read a promising page "
    "in full when a snippet is not enough; prefer reading a source to guessing "
    "from a snippet.\n"
    "- If the first results are thin or off-target, search again with different "
    "terms before settling.\n"
    "- Each tool result lists its sources with an id like [0]. Track those ids "
    "and cite the specific sources that support each part of your answer.\n"
    "- When you have enough to answer well, call submit_finding. Break your "
    "answer into individual claims, and give each claim the ids of the sources "
    "that back it (use only the ids shown in the tool results).\n"
    "- If you cannot find relevant information, call submit_finding with "
    "found_info=false and say so plainly. Never invent facts or sources."
)


async def _noop(event: AgentEvent) -> None:
    return None


async def research(
    sub_question: str,
    *,
    provider: LLMProvider,
    tools: list[Tool],
    emit: Emit = _noop,
    max_iters: int,
) -> Finding:
    """Run the ReAct tool-use loop for one sub-question and return a Finding.

    The model is given the executable ``tools`` plus the ``submit_finding``
    control tool; it searches/reads until it calls ``submit_finding`` (the
    terminal step) or the iteration cap forces a final answer.
    """
    submit = SubmitFinding()
    specs = [*tools, submit]
    executables = {tool.name: tool for tool in tools}
    consulted: list[Source] = []
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=sub_question),
    ]

    # The researcher_start/done lifecycle is emitted by the orchestrator, which
    # knows this researcher's index and the total. The leaf emits only its own
    # internal steps (tool calls, errors, forced finish).
    for _ in range(max_iters):
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

    # Iteration cap hit: force one final submit_finding (found_info is the escape
    # hatch so the model can honestly say it found nothing instead of confabulating).
    await emit(AgentEvent(type="researcher_forced", message="Max iterations reached"))
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
