"""The supervisor: the agent the user talks to.

It is an ordinary conversational agent with an unusual set of tools. Some are
retrieval (search a page, read an uploaded file); the rest are whole sub-agents
behind a tool call: a research run, a fact check, a deep research run started in
the background. There is no router and no fixed set of moves, because the
question "does this need research?" is exactly the judgement a model is good at
and a classifier is bad at.

Sub-agents hand back a summary, never a document. The supervisor writes the
answer itself, in the conversation, out of the same numbered sources its tools
registered, so an answer that took four searches reads like one voice rather
than a stitched-together pipeline.
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents.citations import finalize
from app.agents.language import detect_language
from app.agents.report import text_of
from app.agents.research import Limits, Middleware, render_findings, run_research
from app.agents.schemas import AgentEvent, ResearchResult, Source, Turn
from app.agents.sources import Sources
from app.agents.tools import SearchBackend, retrieval_tools, tagged
from app.prompts import render
from app.prompts.common import today
from app.prompts.supervisor import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

# The supervisor's reply ends with its follow-up suggestions on one line. Parsed
# out by code, so the chips are structured without a second model call and a
# model that forgets the line simply produces no chips.
_SUGGEST = re.compile(r"<suggest>(.*?)</suggest>\s*$", re.IGNORECASE | re.DOTALL)
_MAX_SUGGESTIONS = 3


@dataclass
class Document:
    """An uploaded file, as the supervisor can read it."""

    id: int
    filename: str
    text: str


@dataclass
class Output:
    """A report this conversation has already produced: a deep research run, or
    a fact check. Listed by title and read on demand, never carried in context."""

    id: int
    title: str
    content: str


@dataclass
class Answer:
    """What one turn produced: the reply as the user sees it, the sources it
    cites, and the follow-ups offered under it."""

    text: str
    sources: list[Source] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class ResearchArgs(BaseModel):
    question: str = Field(
        description="A clear, self-contained research question, in the user's "
        "language, carrying the context researchers need"
    )


class DeepResearchArgs(BaseModel):
    question: str = Field(
        description="A clear, self-contained research question, in the user's "
        "language, for a run that will take several minutes"
    )
    title: str = Field(
        description="A short title, a few words in the user's language, naming "
        "the report this will produce"
    )


class ReadDocumentArgs(BaseModel):
    document_id: int = Field(description="The id of the document to read")


class ReadReportArgs(BaseModel):
    report_id: int = Field(description="The id of the report to read")


class FactCheckArgs(BaseModel):
    document_id: int = Field(description="The id of the document to fact-check")
    focus: str = Field(
        default="",
        description="Optional: which part or which kind of claim to concentrate on",
    )


async def _noop(event: AgentEvent) -> None:
    return None


def _no_middleware(agent: str, emit: Emit | None = None, **data) -> list:
    return []


async def respond(
    message: str,
    history: list[Turn],
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    sources: Sources,
    documents: list[Document] | None = None,
    outputs: list[Output] | None = None,
    start_deep_research: Callable[[str, str], Awaitable[str]] | None = None,
    start_fact_check: Callable[[int, str], Awaitable[str]] | None = None,
    on_research: Callable[[ResearchResult], None] | None = None,
    middleware: Middleware = _no_middleware,
    emit: Emit = _noop,
    max_iters: int = 8,
) -> Answer:
    """Answer the latest message, doing whatever work that needs first.

    ``history`` is the conversation before it, one entry per turn. The two
    ``start_*`` callbacks queue a background run and return what to tell the
    user; leaving one out simply removes that tool. ``on_research`` hands each
    research run's full result to a caller that wants to look inside it: the
    eval harness, which cannot otherwise see what happened behind a tool call.
    """
    documents = documents or []
    outputs = outputs or []
    agent = create_agent(
        model=model,
        tools=_tools(
            backend=backend,
            sources=sources,
            documents=documents,
            outputs=outputs,
            model=model,
            middleware=middleware,
            emit=emit,
            start_deep_research=start_deep_research,
            start_fact_check=start_fact_check,
            on_research=on_research,
        ),
        system_prompt=_system_prompt(message, documents, outputs),
        middleware=[
            *middleware("supervisor", emit),
            # Out of rounds means answer with what it has, not fail the turn.
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )
    state = await agent.ainvoke({"messages": _conversation(history, message)})
    return _answer(_last_text(state.get("messages", [])), sources)


def _system_prompt(
    message: str, documents: list[Document], outputs: list[Output]
) -> str:
    rendered = render(
        PROMPT,
        history=[],
        message=message,
        today=today(),
        language=detect_language(message) or "",
    )
    prompt = rendered[0].content or ""
    return "\n\n".join([prompt, _attachments(documents), _outputs(outputs)])


def _attachments(documents: list[Document]) -> str:
    """What is attached to this conversation, by id. Only the names: the text is
    read through the tool, so a long file never sits in the system prompt."""
    if not documents:
        return (
            "<attachments>\nNo documents are attached to this conversation.\n"
            "</attachments>"
        )
    lines = [f"- id {d.id}: {d.filename}" for d in documents]
    return (
        "<attachments>\nDocuments attached to this conversation, readable with "
        "read_document:\n" + "\n".join(lines) + "\n</attachments>"
    )


def _outputs(outputs: list[Output]) -> str:
    """The reports this conversation has produced, by title. Only the titles: a
    report can be long, and read_report fetches the one that matters."""
    if not outputs:
        return "<outputs>\nThis conversation has produced no reports yet.\n</outputs>"
    lines = [f"- id {o.id}: {o.title}" for o in outputs]
    return (
        "<outputs>\nReports produced in this conversation, readable with "
        "read_report:\n" + "\n".join(lines) + "\n</outputs>"
    )


def _conversation(history: list[Turn], message: str) -> list[BaseMessage]:
    """The thread as real messages: each earlier turn its own, the new message
    last. Not one blob of text, so the model sees who said what."""
    messages: list[BaseMessage] = [
        HumanMessage(turn.content) if turn.role == "user" else AIMessage(turn.content)
        for turn in history
    ]
    messages.append(HumanMessage(message))
    return messages


def _tools(
    *,
    backend: SearchBackend,
    sources: Sources,
    documents: list[Document],
    outputs: list[Output],
    model: BaseChatModel,
    middleware: Middleware,
    emit: Emit,
    start_deep_research: Callable[[str, str], Awaitable[str]] | None,
    start_fact_check: Callable[[int, str], Awaitable[str]] | None,
    on_research: Callable[[ResearchResult], None] | None,
) -> list[StructuredTool]:
    by_id = {document.id: document for document in documents}
    reports = {output.id: output for output in outputs}

    async def read_document(document_id: int) -> str:
        document = by_id.get(document_id)
        if document is None:
            known = ", ".join(str(i) for i in by_id) or "none"
            return f"No document with id {document_id}. Attached ids: {known}."
        await emit(
            AgentEvent(
                type="document_read",
                message=f"Reading {document.filename}",
                data={"agent": "supervisor", "document": document.filename},
            )
        )
        return tagged("document", document.text, filename=document.filename)

    async def read_report(report_id: int) -> str:
        output = reports.get(report_id)
        if output is None:
            known = ", ".join(str(i) for i in reports) or "none"
            return f"No report with id {report_id}. Reports here: {known}."
        return tagged("report", output.content, title=output.title)

    async def research(question: str) -> str:
        result = await run_research(
            question,
            model=model,
            backend=backend,
            sources=sources,
            emit=emit,
            middleware=middleware,
            limits=Limits.normal(),
        )
        if on_research is not None:
            on_research(result)
        if not result.points:
            return (
                "The researchers came back with nothing usable for: "
                f"{question}. Say so rather than answering from memory."
            )
        return render_findings(result)

    async def deep_research(question: str, title: str) -> str:
        if start_deep_research is None:
            return "Deep research is not available here. Use research instead."
        return await start_deep_research(question, title)

    async def fact_check(document_id: int, focus: str = "") -> str:
        if start_fact_check is None:
            return "Fact-checking is not available here."
        if document_id not in by_id:
            known = ", ".join(str(i) for i in by_id) or "none"
            return f"No document with id {document_id}. Attached ids: {known}."
        return await start_fact_check(document_id, focus)

    tools = [
        *retrieval_tools(backend, sources, emit=emit, agent="supervisor"),
        StructuredTool.from_function(
            coroutine=research,
            name="research",
            description=(
                "Research a question properly: it is split into sub-questions, a "
                "researcher works each one in parallel on the live web, and you "
                "get their claims back with the source numbers behind them. Takes "
                "up to a couple of minutes. Use it for anything a search snippet "
                "cannot settle."
            ),
            args_schema=ResearchArgs,
        ),
    ]
    if outputs:
        tools.append(
            StructuredTool.from_function(
                coroutine=read_report,
                name="read_report",
                description=(
                    "Read the full text of a report this conversation has already "
                    "produced. The outputs list gives each one's id. Call this "
                    "before answering about a report or building on one."
                ),
                args_schema=ReadReportArgs,
            )
        )
    if documents:
        tools.append(
            StructuredTool.from_function(
                coroutine=read_document,
                name="read_document",
                description=(
                    "Read the full text of a document attached to this "
                    "conversation. The attachments list gives each one's id."
                ),
                args_schema=ReadDocumentArgs,
            )
        )
    if start_fact_check is not None and documents:
        tools.append(
            StructuredTool.from_function(
                coroutine=fact_check,
                name="fact_check",
                description=(
                    "Check an attached document's claims against the web. It runs "
                    "in the background, writes its own report into the user's "
                    "Outputs, and returns a note to pass on. Do not wait for it."
                ),
                args_schema=FactCheckArgs,
            )
        )
    if start_deep_research is not None:
        tools.append(
            StructuredTool.from_function(
                coroutine=deep_research,
                name="deep_research",
                description=(
                    "Start a deep research run: much wider than research, several "
                    "minutes long, and it writes its own report into the user's "
                    "Outputs. It runs in the background and returns at once with a "
                    "note to pass on. Do not wait for it or invent its findings."
                ),
                args_schema=DeepResearchArgs,
            )
        )
    return tools


def _last_text(messages: list) -> str:
    """The reply: the last thing the agent wrote that was not a tool call."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = text_of(message)
            if text.strip():
                return text
    return ""


def _answer(written: str, sources: Sources) -> Answer:
    """The reply as the user sees it: suggestions split off, invented citations
    dropped, and only the sources it really cites kept."""
    text, suggestions = _split_suggestions(written)
    if not text.strip():
        logger.warning("the supervisor produced no reply")
        return Answer(text="", sources=[], suggestions=suggestions)
    # keep_uncited=False: an answer that cites nothing should not drag a source
    # list behind it, unlike a report, whose sources are half the point.
    content, cited, stripped = finalize(text, sources.all, keep_uncited=False)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
    return Answer(text=content.strip(), sources=cited, suggestions=suggestions)


def _split_suggestions(written: str) -> tuple[str, list[str]]:
    match = _SUGGEST.search(written)
    if match is None:
        return written, []
    offered = [part.strip() for part in match.group(1).split("|")]
    return written[: match.start()], [s for s in offered if s][:_MAX_SUGGESTIONS]
