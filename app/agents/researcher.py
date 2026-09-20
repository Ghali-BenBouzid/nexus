"""One researcher: a sub-agent that answers a single sub-question from the web.

It searches, reads promising pages, and finishes by submitting claims, each with
the sources that back it. The loop itself is LangChain's; what lives here is the
part that makes a finding trustworthy:

- Sources are registered by code, in the turn's shared registry, as the tools
  return them. A claim can only cite something that was really retrieved, and
  the number it cites means the same thing everywhere else in the turn.
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
from pydantic import ValidationError

from app.agents.language import detect_language
from app.agents.model import Deadline
from app.agents.schemas import AgentEvent, Claim, Finding
from app.agents.sources import Sources
from app.agents.tools import SearchBackend, SubmitFindingArgs, retrieval_tools
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.researcher import PROMPT

Emit = Callable[[AgentEvent], Awaitable[None]]


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("research")
async def research_one(
    sub_question: str,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    middleware: list[AgentMiddleware] | None = None,
    emit: Emit = _noop,
    max_iters: int = 3,
    deadline: float | None = None,
) -> Finding:
    """Answer one sub-question and return what was found, with its sources.

    The registry is the researcher's own: its claims cite into its own source
    list, and the caller merges that into the run's numbering. That keeps a
    finding self-contained, which is what lets a deep run checkpoint one.
    """
    sources = Sources()
    agent = create_agent(
        model=model,
        tools=retrieval_tools(backend, sources, emit=emit, agent="researcher"),
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

    return _finding(sub_question, submission, sources)


def _system_prompt(sub_question: str) -> str:
    messages = render(
        PROMPT,
        sub_question=sub_question,
        today=today(),
        language=detect_language(sub_question) or "",
    )
    return messages[0].content or ""


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


def _finding(sub_question: str, submission: Any, sources: Sources) -> Finding:
    if submission is None:
        return Finding(
            sub_question=sub_question, sources=list(sources.all), found_info=False
        )
    claims = [
        Claim(text=claim.text, source_ids=sources.valid(claim.cited_source_ids))
        for claim in submission.claims
        if claim.text.strip()
    ]
    return Finding(
        sub_question=sub_question,
        claims=claims,
        sources=list(sources.all),
        found_info=submission.found_info,
    )


def _out_of_time(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline
