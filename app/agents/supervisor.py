"""The supervisor: the top-level agent the user talks to in a conversation.

It runs a small tool-using loop over the conversation so far. It can read the
full reports already produced and do a quick web check, then commit to exactly
one of three actions:

- ``answer`` — reply directly in chat from the conversation and its reports.
- ``compose`` — synthesize a new, longer report by merging and expanding the
  reports already gathered, with no new web research.
- ``research`` — start a fresh research run (rewriting the message into a
  self-contained query), for genuinely new information.

The terminal action is a forced function call (answer / compose_report /
research); read_reports / web_search / fetch_page are intermediate tools it may
call first. On a malformed or exhausted loop it falls back to ``research`` on the
raw message: doing the work beats a hollow answer.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import AgentEvent
from app.agents.tools import (
    BaseTool,
    BaseToolSpec,
    FetchPage,
    SearchBackend,
    ToolResult,
    WebSearch,
)

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]


class SupervisorDecision(BaseModel):
    action: Literal["answer", "compose", "research"]
    query: str = ""  # research: the self-contained research query
    reply: str = ""  # answer: the direct chat reply
    instructions: str = ""  # compose: how to merge/expand the existing reports
    title: str = ""  # research/compose: a short title for the report artifact


# --- the supervisor's tools -------------------------------------------------


class ReadReportsArgs(BaseModel):
    pass  # no arguments: it reads every report in the conversation


class ReadReports(BaseTool):
    name = "read_reports"
    description = (
        "Read the full text of the research reports already produced in this "
        "conversation, so you can answer from them or merge them. The conversation "
        "only shows excerpts; call this for the complete text."
    )
    args_model = ReadReportsArgs

    def __init__(self, reports: list[tuple[str, str]]) -> None:
        # (original prompt, full report text), in order produced
        self.reports = reports

    async def _run(self, args: BaseModel) -> ToolResult:
        if not self.reports:
            return ToolResult(content="No reports have been produced yet.")
        blocks = [
            f"Report {index} (for: {prompt}):\n{content}"
            for index, (prompt, content) in enumerate(self.reports, start=1)
        ]
        return ToolResult(content="\n\n---\n\n".join(blocks))


class AnswerArgs(BaseModel):
    reply: str = Field(
        default="",
        description="the reply to the user, in the user's language, grounded only "
        "in the conversation and the reports already gathered",
    )


class Answer(BaseToolSpec):
    name = "answer"
    description = (
        "Reply directly to the user from the conversation and the reports already "
        "gathered, with no new research. Use for questions, summaries, and "
        "clarifications the existing material already covers."
    )
    args_model = AnswerArgs


class ComposeReportArgs(BaseModel):
    instructions: str = Field(
        default="",
        description="what to synthesize: which reports to merge and how to expand "
        "them into one longer, more comprehensive report, in the user's language",
    )
    title: str = Field(
        default="",
        description="a short title (a few words, in the user's language) naming the "
        "composed report",
    )


class ComposeReport(BaseToolSpec):
    name = "compose_report"
    description = (
        "Produce a new, longer report by merging and expanding the reports already "
        "in this conversation, with NO new web search. Use this when the user asks "
        "to combine, lengthen, deepen, or rewrite existing reports into one."
    )
    args_model = ComposeReportArgs


class ResearchArgs(BaseModel):
    query: str = Field(
        default="",
        description="a clear, self-contained research question, in the user's "
        "language, capturing what to find and the relevant context",
    )
    title: str = Field(
        default="",
        description="a short title (a few words, in the user's language) naming the "
        "report this research will produce",
    )


class Research(BaseToolSpec):
    name = "research"
    description = (
        "Start a fresh web research run. Use only when the answer needs new "
        "information the existing reports do not contain."
    )
    args_model = ResearchArgs


_TERMINAL = {"answer", "compose_report", "research"}

_SYSTEM_PROMPT = (
    "You are the controller of a research assistant: the agent the user talks to. "
    "You see the conversation so far and the reports already produced, and you "
    "decide how to handle the user's latest message.\n"
    "You have tools to gather what you need first:\n"
    "- read_reports: read the full text of the reports already produced. Use it "
    "before answering from or merging them, because the conversation only shows "
    "excerpts.\n"
    "- web_search / fetch_page: a quick web check when you need one small fact to "
    "answer directly; for anything substantial, prefer research.\n"
    "Then commit to exactly ONE terminal action:\n"
    "- answer: reply directly from the conversation and its reports (a question "
    "about a report, a summary, a clarification, a follow-up already covered).\n"
    "- compose_report: merge and expand the existing reports into one new, longer, "
    "more comprehensive report, with no new search. Choose this when the user asks "
    "to combine, lengthen, or deepen reports already produced, rather than starting "
    "a new search.\n"
    "- research: start a fresh web research run, only when genuinely new "
    "information is needed.\n"
    "When you call research or compose_report, also give a short title (a few "
    "words, in the user's language) naming the report it will produce.\n"
    "Always respond in the same language as the user. Never invent facts. When in "
    "doubt between answering and researching, prefer research; but if the user is "
    "asking to expand or combine reports you already have, prefer compose_report "
    "over launching another search."
)


async def _noop(event: AgentEvent) -> None:
    return None


async def decide(
    message: str,
    context: str,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    reports: list[tuple[str, str]],
    emit: Emit = _noop,
    max_iters: int = 4,
) -> SupervisorDecision:
    """Route the latest message through a small tool loop. ``context`` is the
    rendered conversation; ``reports`` is the full text of prior reports (exposed
    via read_reports). The provider and backend must already be open."""
    read_reports = ReadReports(reports)
    web_search = WebSearch(backend=backend)
    fetch_page = FetchPage(backend=backend)
    tools = [
        read_reports,
        web_search,
        fetch_page,
        Answer(),
        ComposeReport(),
        Research(),
    ]
    executables = {
        read_reports.name: read_reports,
        web_search.name: web_search,
        fetch_page.name: fetch_page,
    }
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(
            role="user",
            content=f"{context}\n\nLatest message from the user:\n{message}",
        ),
    ]

    for _ in range(max_iters):
        response = await provider.generate(
            messages, tools=tools, tool_choice="required"
        )
        messages.append(_assistant_message(response))

        if not response.tool_calls:
            messages.append(Message(role="user", content="Call one of the tools."))
            continue

        call = response.tool_calls[0]
        if call.name in _TERMINAL:
            decision = _decision_from(call.name, call.args, message)
            if decision is not None:
                return decision
            # Malformed terminal call: feed the error back and let it retry within
            # the budget, like the researcher's malformed-submit handling.
            messages.append(
                Message(
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content="Invalid arguments. Call the tool again with valid ones.",
                )
            )
            continue

        result = await _run_tool(call.id, call.name, call.args, executables, emit)
        messages.append(
            Message(
                role="tool",
                tool_call_id=call.id,
                name=call.name,
                content=result.content,
            )
        )

    # Budget exhausted without a clean decision: do the work rather than answer
    # hollowly (mirrors the parse-failure default).
    return SupervisorDecision(action="research", query=message)


def _decision_from(name: str, args: dict, message: str) -> SupervisorDecision | None:
    try:
        if name == "answer":
            reply = AnswerArgs(**args).reply.strip()
            return SupervisorDecision(action="answer", reply=reply) if reply else None
        if name == "compose_report":
            parsed = ComposeReportArgs(**args)
            return SupervisorDecision(
                action="compose",
                instructions=parsed.instructions.strip(),
                title=parsed.title.strip(),
            )
        if name == "research":
            parsed = ResearchArgs(**args)
            return SupervisorDecision(
                action="research",
                query=parsed.query.strip() or message,
                title=parsed.title.strip(),
            )
    except ValidationError:
        return None
    return None


async def _run_tool(
    call_id: str,
    name: str,
    args: dict,
    executables: dict[str, BaseTool],
    emit: Emit,
) -> ToolResult:
    tool = executables.get(name)
    if tool is None:
        return ToolResult(content=f"Unknown tool: {name}")
    await emit(
        AgentEvent(
            type="supervisor_tool",
            message=f"{name}({args})",
            data={"tool": name, "args": args},
        )
    )
    try:
        return await tool.execute(**args)
    except Exception as exc:  # a failed tool call must not kill the routing loop
        await emit(AgentEvent(type="tool_error", message=f"{name} failed: {exc}"))
        return ToolResult(content=f"Tool {name} failed: {exc}")


def _assistant_message(response: LLMResponse) -> Message:
    return Message(
        role="assistant",
        content=response.text,
        tool_calls=response.tool_calls,
    )
