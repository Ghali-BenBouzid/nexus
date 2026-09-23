"""The fact checker: an agent that reads a document and tests it against the web.

It is a sub-agent in both directions. The supervisor can call it as a tool when
a conversation turns on whether a document is right, and the user can start it
from a button on the document itself. Either way it does the same thing: pick
the claims the document rests on, search for what independent sources say, and
write its own report.

Its report is its final message rather than a second call to a writer: by then
it has read everything it is going to read, and asking a separate model to
re-say it would only add a hop and a chance to drift from what was actually
found.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from app.agents.citations import finalize
from app.agents.language import detect_language
from app.agents.model import Deadline, LastStep
from app.agents.report import text_of
from app.agents.schemas import AgentEvent, Report
from app.agents.sources import Sources
from app.agents.tools import SearchBackend, retrieval_tools, tagged
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.factcheck import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

NOTHING_CHECKED = (
    "The fact check produced nothing readable. The document may hold no "
    "checkable claims, or the run was cut short."
)


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("fact_check")
async def fact_check(
    text: str,
    *,
    filename: str,
    model: BaseChatModel,
    backend: SearchBackend,
    sources: Sources,
    middleware: list[AgentMiddleware] | None = None,
    emit: Emit = _noop,
    focus: str = "",
    max_iters: int = 12,
    deadline: float | None = None,
) -> Report:
    """Check ``text`` against the web and write the report."""
    await emit(
        AgentEvent(
            type="factcheck_start",
            message=f"Fact-checking {filename}",
            data={"agent": "fact_checker", "document": filename},
        )
    )
    agent = create_agent(
        model=model,
        tools=retrieval_tools(backend, sources, emit=emit, agent="fact_checker"),
        system_prompt=_system_prompt(text, focus),
        middleware=[
            *(middleware or []),
            # Out of time or out of rounds means write the report from what it
            # has read, not fail: the searching is already paid for.
            Deadline(deadline),
            LastStep(
                max_iters,
                "This is your last step: there are no more searches after it. "
                "Write your verdicts now from what you have already found, and "
                "say which claims you could not check.",
            ),
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )
    state = await agent.ainvoke(
        {"messages": [("user", _document(text, filename, focus))]}
    )
    written = _last_text(state.get("messages", []))
    await emit(
        AgentEvent(
            type="factcheck_done",
            message=f"Fact check written for {filename}",
            data={"agent": "fact_checker", "document": filename},
        )
    )
    if not written.strip():
        logger.warning("the fact checker for %s produced no report", filename)
        return Report(content=NOTHING_CHECKED, sources=[])

    content, cited, stripped = finalize(written, sources.all)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
    return Report(content=content, sources=cited)


def _system_prompt(text: str, focus: str) -> str:
    messages = render(
        PROMPT,
        document="",
        focus=focus.strip(),
        today=today(),
        language=detect_language(text[:2000]) or "",
    )
    return messages[0].content or ""


def _document(text: str, filename: str, focus: str) -> str:
    """The document as the checker receives it: tagged as material to read, with
    the user's focus outside the tag so a document cannot pose as one."""
    block = tagged("document", text, filename=filename)
    if focus.strip():
        return f"{block}\n\nThe user asked you to focus on: {focus.strip()}"
    return block


def _last_text(messages: list) -> str:
    """The report: the last thing the agent wrote that was not a tool call."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = text_of(message)
            if text.strip():
                return text
    return ""
