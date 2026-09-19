"""The supervisor: the agent the user talks to.

It sees the conversation and the documents attached to it, can read the reports
already produced and check one small fact on the web, and then commits to one of
three moves:

- ``answer``: reply from the conversation and what it has read.
- ``compose``: merge the conversation's reports into one longer report.
- ``research``: send researchers after genuinely new information.

The loop is LangChain's; the decision is a structured output, so "which move" is
a schema the model fills rather than prose someone has to parse. Reading reports
and searching are ordinary tools it may use first, as many times as it judges
useful.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents.language import detect_language
from app.agents.schemas import AgentEvent, Turn
from app.agents.tools import (
    FetchPageArgs,
    SearchBackend,
    WebSearchArgs,
    fetch_page_text,
    tagged,
    web_search_results,
)
from app.prompts import render
from app.prompts.common import today
from app.prompts.supervisor import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]


class SupervisorDecision(BaseModel):
    action: Literal["answer", "compose", "research"]
    query: str = ""  # research: the self-contained research query
    reply: str = ""  # answer: the direct chat reply
    instructions: str = ""  # compose: how to merge/expand the existing reports
    title: str = ""  # research/compose: a short title for the report artifact


class Decision(BaseModel):
    """What the supervisor commits to, once it has read what it needs."""

    action: Literal["answer", "compose_report", "research"] = Field(
        description="answer: reply now from the conversation and its reports. "
        "compose_report: merge those reports into one longer report, no new "
        "search. research: send researchers after new information."
    )
    reply: str = Field(
        default="",
        description="answer only: the reply to the user, in the user's language, "
        "grounded only in the conversation and the reports already gathered",
    )
    query: str = Field(
        default="",
        description="research only: a clear, self-contained research question in "
        "the user's language, carrying the context a researcher needs",
    )
    instructions: str = Field(
        default="",
        description="compose_report only: which reports to merge and how to expand "
        "them into one longer report, in the user's language",
    )
    title: str = Field(
        default="",
        description="research and compose_report: a short title, a few words in "
        "the user's language, naming the report this will produce",
    )


async def _noop(event: AgentEvent) -> None:
    return None


async def decide(
    message: str,
    history: list[Turn],
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    reports: list[tuple[str, str]],
    middleware: list[AgentMiddleware] | None = None,
    emit: Emit = _noop,
    max_iters: int = 4,
) -> SupervisorDecision:
    """Route the latest message. ``history`` is the conversation before it, one
    entry per turn; ``reports`` is the full text of the reports produced in it,
    which the supervisor reads on demand rather than carrying in context."""
    agent = create_agent(
        model=model,
        tools=_tools(backend, reports),
        system_prompt=_system_prompt(message),
        response_format=ToolStrategy(Decision),
        middleware=[
            *(middleware or []),
            # Out of rounds means decide now with what it has, not fail the turn.
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )

    state = await agent.ainvoke({"messages": _conversation(history, message)})
    decision = state.get("structured_response")
    if decision is None:
        # Budget spent without committing: do the work rather than answer hollowly.
        return SupervisorDecision(action="research", query=message)
    return _decision(decision, message)


def _system_prompt(message: str) -> str:
    rendered = render(
        PROMPT,
        history=[],
        message=message,
        today=today(),
        language=detect_language(message) or "",
    )
    return rendered[0].content or ""


def _conversation(history: list[Turn], message: str) -> list[BaseMessage]:
    """The thread as real messages: each earlier turn its own, the new message
    last. A report inside a turn is already tagged as retrieved material."""
    messages: list[BaseMessage] = [
        HumanMessage(turn.content) if turn.role == "user" else AIMessage(turn.content)
        for turn in history
    ]
    messages.append(HumanMessage(message))
    return messages


def _tools(
    backend: SearchBackend, reports: list[tuple[str, str]]
) -> list[StructuredTool]:
    async def read_reports() -> str:
        if not reports:
            return "No reports have been produced yet."
        blocks = [
            tagged("report", content, index=str(index), question=prompt)
            for index, (prompt, content) in enumerate(reports, start=1)
        ]
        return "\n\n---\n\n".join(blocks)

    async def web_search(query: str, max_results: int = 5) -> str:
        return (await web_search_results(backend, query, max_results)).content

    async def fetch_page(url: str) -> str:
        return (await fetch_page_text(backend, url)).content

    return [
        StructuredTool.from_function(
            coroutine=read_reports,
            name="read_reports",
            description=(
                "Read the full text of the research reports already produced in "
                "this conversation, so you can answer from them or merge them. The "
                "conversation only shows excerpts; call this for the complete text."
            ),
        ),
        StructuredTool.from_function(
            coroutine=web_search,
            name="web_search",
            description=(
                "Run a web search for one small fact you need to answer directly. "
                "For anything substantial, choose research instead."
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


def _decision(decision: Decision, message: str) -> SupervisorDecision:
    if decision.action == "answer" and decision.reply.strip():
        return SupervisorDecision(action="answer", reply=decision.reply.strip())
    if decision.action == "compose_report":
        return SupervisorDecision(
            action="compose",
            instructions=decision.instructions.strip(),
            title=decision.title.strip(),
        )
    # research, and an answer with nothing in it: doing the work beats a blank reply
    return SupervisorDecision(
        action="research",
        query=decision.query.strip() or message,
        title=decision.title.strip(),
    )


__all__ = ["Decision", "SupervisorDecision", "decide"]
