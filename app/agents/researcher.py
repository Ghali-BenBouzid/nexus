"""One researcher: a sub-agent that answers a single sub-question from the web.

It searches, reads promising pages, and finishes by submitting claims, each with
the sources that back it. The loop itself is LangChain's; what lives here is the
part that makes a finding trustworthy:

- Sources are registered by code as the tools return them, so a claim can only
  cite something that was really retrieved.
- Running out of rounds or out of time does not lose the work: the researcher is
  asked once more, with the submit schema forced, to say what it found.
- An empty-handed finding is a real answer (``found_info=False``), not a failure.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from app.agents.language import detect_language
from app.agents.model import Deadline
from app.agents.schemas import AgentEvent, Finding, FindingClaim, Source
from app.agents.tools import (
    FetchPageArgs,
    SearchBackend,
    SubmitFindingArgs,
    WebSearchArgs,
    fetch_page_text,
    web_search_results,
)
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
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
    model: BaseChatModel,
    backend: SearchBackend,
    middleware: list[AgentMiddleware] | None = None,
    emit: Emit = _noop,
    max_iters: int = 3,
    deadline: float | None = None,
) -> Finding:
    """Answer one sub-question and return what was found, with its sources."""
    consulted: list[Source] = []
    tools = _tools(backend, consulted, emit)
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=_system_prompt(sub_question),
        response_format=ToolStrategy(
            SubmitFindingArgs,
            # A malformed submission is fed back rather than lost: the researcher
            # has already paid for the searching by this point.
            handle_errors="submit_finding arguments were invalid: {error}. "
            "Call it again with valid arguments.",
        ),
        middleware=[
            *(middleware or []),
            # Both end the loop rather than raise: an out-of-rounds or out-of-time
            # researcher still has findings worth submitting, which the forced
            # finish below collects.
            Deadline(deadline),
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )

    state = await agent.ainvoke({"messages": [("user", sub_question)]})
    submission = state.get("structured_response")
    if submission is None:
        reason = "Time budget reached" if _out_of_time(deadline) else "Max rounds"
        await emit(AgentEvent(type="researcher_forced", message=reason))
        submission = await _forced_finish(model, state["messages"])

    return _finding(sub_question, submission, consulted)


def _system_prompt(sub_question: str) -> str:
    messages = render(
        PROMPT,
        sub_question=sub_question,
        today=today(),
        language=detect_language(sub_question) or "",
    )
    return messages[0].content or ""


def _tools(
    backend: SearchBackend, consulted: list[Source], emit: Emit
) -> list[StructuredTool]:
    """The researcher's two tools. Each registers what it retrieved into
    ``consulted`` and hands back the ids, which are the only ones a claim may
    cite. A failure is told to the researcher and to the feed, never raised: one
    dead search should cost a search, not the sub-question."""

    async def retrieve(what: str, retrieving) -> str:
        try:
            result = await retrieving()
        except Exception as exc:  # noqa: BLE001 -- a failed tool is not a failed run
            await emit(
                AgentEvent(
                    type="tool_error",
                    message=f"{what} failed: {exc}",
                    data={"agent": "researcher", "tool": what},
                )
            )
            return f"{what} failed: {exc}. Try a different approach."
        return _with_ids(result.content, result.sources, consulted)

    async def web_search(query: str, max_results: int = 5) -> str:
        return await retrieve(
            "web_search", lambda: web_search_results(backend, query, max_results)
        )

    async def fetch_page(url: str) -> str:
        return await retrieve("fetch_page", lambda: fetch_page_text(backend, url))

    return [
        StructuredTool.from_function(
            coroutine=web_search,
            name="web_search",
            description=(
                "Run a web search for a query and return up to max_results results."
            ),
            args_schema=WebSearchArgs,
        ),
        StructuredTool.from_function(
            coroutine=fetch_page,
            name="fetch_page",
            description=(
                "Fetch a web page by URL and return its cleaned full text, for when "
                "a search snippet is promising but insufficient."
            ),
            args_schema=FetchPageArgs,
        ),
    ]


def _with_ids(content: str, sources: list[Source], consulted: list[Source]) -> str:
    """Register a tool's sources and append the legend the model cites from."""
    if not sources:
        return content
    lines = []
    for source in sources:
        consulted.append(source)
        lines.append(f"[{len(consulted) - 1}] {source.title} ({source.url})")
    return f"{content}\n\nCite these sources by id:\n" + "\n".join(lines)


async def _forced_finish(model: BaseChatModel, messages: list[Any]) -> Any:
    """Ask once more, with the schema forced, so a researcher that ran out of
    rounds still reports what it read instead of returning nothing."""
    bound = model.bind_tools([SubmitFindingArgs], tool_choice="any")
    reply = await bound.ainvoke(
        [
            *messages,
            (
                "user",
                "Submit what you found now with submit_finding, from what you have "
                "already read. Set found_info=false if you found nothing relevant.",
            ),
        ]
    )
    for call in reply.tool_calls or []:
        try:
            return SubmitFindingArgs(**call["args"])
        except ValidationError:
            continue
    return None


def _finding(sub_question: str, submission: Any, consulted: list[Source]) -> Finding:
    if submission is None:
        return Finding(
            sub_question=sub_question,
            claims=[],
            consulted_sources=consulted,
            found_info=False,
        )
    claims = [
        FindingClaim(
            text=claim.text,
            sources=[
                consulted[i] for i in claim.cited_source_ids if 0 <= i < len(consulted)
            ],
        )
        for claim in submission.claims
    ]
    return Finding(
        sub_question=sub_question,
        claims=claims,
        consulted_sources=consulted,
        found_info=submission.found_info,
    )


def _out_of_time(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline
