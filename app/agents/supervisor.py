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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.agents.citations import finalize
from app.agents.language import detect_language
from app.agents.model import REASONING, STAGE_KEY, LastStep
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
    """What one turn produced: the reply as the user sees it and the sources it
    cites."""

    text: str
    sources: list[Source] = field(default_factory=list)


class ResearchArgs(BaseModel):
    question: str = Field(
        description="A clear, self-contained research question, in the user's "
        "language, carrying the context researchers need"
    )


class DeepResearchArgs(BaseModel):
    question: str = Field(
        description="The user's question, self-contained and in their language, "
        "as they would ask it: not a syllabus or a list of topics to cover"
    )
    goal: str = Field(
        description="The brief for the run: what the user wants the report for, "
        "depth on a few areas or a broad first look, the areas to focus on, and "
        "what you decided for them"
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
    title: str = Field(
        description="A short title in the user's language naming the report "
        "this will produce and the document it checks"
    )
    focus: str = Field(
        default="",
        description="Optional: which part or which kind of claim to concentrate on",
    )


class SteerArgs(BaseModel):
    run_id: int = Field(description="The id of the running deep research run")
    note: str = Field(
        description="What the user wants changed, self-contained and in their "
        "words: the corrected assumption, the changed decision, the new focus"
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
    start_deep_research: Callable[[str, str, str], Awaitable[str]] | None = None,
    start_fact_check: Callable[[int, str, str], Awaitable[str]] | None = None,
    on_research: Callable[[ResearchResult], None] | None = None,
    middleware: Middleware = _no_middleware,
    emit: Emit = _noop,
    max_iters: int = 8,
    mode: str = "answer",
    running: list[Output] | None = None,
    steer_deep_research: Callable[[int, str], Awaitable[str]] | None = None,
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
    running = running or []
    agent = create_agent(
        model=model,
        tools=[
            *_tools(
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
            # Only while a deep run is working here: every other turn has
            # exactly the tools and the prompt it had before steering existed.
            *_steer_tool(running, steer_deep_research),
        ],
        system_prompt=_system_prompt(
            message, documents, outputs, mode=mode, running=running
        ),
        middleware=[
            *middleware("supervisor", emit),
            # Out of rounds means answer with what it has, not fail the turn,
            # and it is told so on the last one rather than cut off.
            LastStep(
                max_iters,
                "This is your last step: no more tool calls after it. Answer the "
                "user now with what you have, and say plainly what you could not "
                "finish.",
            ),
            *([RunClaimCheck(mode)] if mode in _STARTERS else []),
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )
    state = await _stream(agent, _conversation(history, message), emit)
    return _answer(_last_text(state.get("messages", [])), sources)


# The supervisor's own stage. A sub-agent called through a tool runs under its
# own stage, so this is what separates the supervisor's thinking from a
# researcher's: both run create_agent graphs whose model node is called "model",
# and their chunks would otherwise interleave into the user's reply.
_OWN_STAGE = "supervisor"


async def _stream(agent, messages: list[BaseMessage], emit: Emit) -> dict:
    """Run the agent, emitting its thinking and its reply as they are produced.

    Two stream modes at once: ``messages`` for the chunks, ``values`` for the
    state we return, which is the same state ``ainvoke`` would have given us.
    The caller is unchanged; only the timing of what the user sees is.
    """
    state: dict = {}
    async for mode, payload in agent.astream(
        {"messages": messages}, stream_mode=["messages", "values"]
    ):
        if mode == "values":
            state = payload
            continue
        chunk, _ = payload
        # Two things are not the answer being written. A tool's result, which
        # this stream carries alongside the model's own chunks; and a sub-agent's
        # chunks, which look identical because a sub-agent is a create_agent
        # graph too, with a model node called "model" just the same.
        if not isinstance(chunk, AIMessageChunk):
            continue
        extra = chunk.additional_kwargs or {}
        if extra.get(STAGE_KEY, _OWN_STAGE) != _OWN_STAGE:
            continue
        thought = extra.get(REASONING)
        if thought:
            await emit(AgentEvent(type="thought", message=thought))
        elif chunk.text:
            await emit(AgentEvent(type="token", message=chunk.text))
    return state


def _system_prompt(
    message: str,
    documents: list[Document],
    outputs: list[Output],
    *,
    mode: str = "answer",
    running: list[Output] | None = None,
) -> str:
    rendered = render(
        PROMPT,
        history=[],
        message=message,
        today=today(),
        language=detect_language(message) or "",
    )
    prompt = rendered[0].content or ""
    parts = [prompt, _attachments(documents), _outputs(outputs)]
    if mode in _MODES:
        parts.append(_MODES[mode])
    if running:
        parts.append(_running(running))
    return "\n\n".join(parts)


def _running(running: list[Output]) -> str:
    """The deep runs still working in this conversation. Without this the
    supervisor could not tell a run was going at all, and a user changing
    their mind got a second run, or a promise that the first had changed."""
    lines = [f"- id {o.id}: {o.title}" for o in running]
    return (
        "<running>\nDeep research runs still working in this conversation, not "
        "readable yet:\n" + "\n".join(lines) + "\nWhen the user changes their "
        "mind about one, corrects an assumption it was started with, or wants its "
        "focus changed, pass that to it with steer_deep_research instead of "
        "starting another run. Say what the tool says will happen, nothing more."
        "\n</running>"
    )


def _steer_tool(
    running: list[Output],
    steer: Callable[[int, str], Awaitable[str]] | None,
) -> list[StructuredTool]:
    if not running or steer is None:
        return []
    return [
        StructuredTool.from_function(
            coroutine=steer,
            name="steer_deep_research",
            description=(
                "Pass a correction or a change of mind to a deep research run "
                "that is still working: its lead reads it before its next step "
                "and adjusts what it researches next. Returns what will happen, "
                "to pass on; the run is not restarted and nothing already found "
                "is lost."
            ),
            args_schema=SteerArgs,
        )
    ]


# Beside the attachments and the outputs, because it is the same kind of thing:
# a fact about this conversation right now, not how Nexus works in general.
# The toggle is a strong signal of what the user wants, not an instruction to
# run whatever arrives: "hi" and "don't research this" arrive with it too, and
# telling those apart from a real subject is the judgement this agent is for.
_DEEP_MODE = """\
<mode>
The user has switched to deep research mode for this message. They want a \
question answered properly, so when this message is a subject or question \
worth researching in depth, start deep_research on it, with a short title that \
names the subject. Do not answer it with a quick research pass instead: \
choosing this mode is the user asking for depth.

A deep run is shaped by what the user wants from it, so before starting one, \
make sure you know:
- what they want the report for: a decision, learning a subject, writing \
something, checking an idea;
- whether they want depth on a few areas or a broad first look at the subject \
(to go deep on part of it in a later run);
- which areas matter to them, if they already know.
When the message or the conversation already makes this clear, start at once. \
A bare topic or a broad request ("quantum computing", "teach me about X") \
does not: it says what to research, not what they want from it, so ask before \
starting, not about the plan but about what they \
want: short, with two or three concrete options each so answering takes a \
second, and always one option that leaves it to you ("your call"). If the \
answer still leaves it unclear, ask again, more narrowly. Only when they \
leave it to you, by choosing that option or saying to just go, choose what \
serves the question best and start; never decide on their behalf that they \
left it to you.

Pass all of it in the goal argument: what the report is for, depth or \
breadth, the areas to focus on, and what you decided for them. Keep the \
question the user's own question rather than a list of topics.

When this message is not something to research (a greeting, small talk, a \
question about Nexus, or a request not to research), do not start a run. \
Answer it as you normally would, and say in a sentence what deep research is \
for and what to send to start one.

When the subject itself is too vague to research at all, pin it down the \
same way before starting: a deep run takes several minutes, and a report built \
on a guess about what they meant wastes all of them.
</mode>"""

# The same principle for fact checking: the mode says what the user is after,
# and the thread is still this agent's to answer.
_FACTCHECK_MODE = """\
<mode>
The user has switched to fact check mode for this message. They want a \
document checked against the web. Start fact_check on the document they mean: \
the one sent with this message, or the one they name. When several are \
attached and the message does not say which, check the ones sent with it, or \
ask which when none were. Whatever the message says about what to look at \
goes in as the focus.

When no document is attached, do not start anything: say that a fact check \
works on an uploaded file and ask them to attach the one to check.

When this message is not asking for a check (a greeting, small talk, a \
question about Nexus, or a request not to check), answer it as you normally \
would, and say in a sentence what fact check mode is for.
</mode>"""

_MODES = {"deep": _DEEP_MODE, "factcheck": _FACTCHECK_MODE}

# The tool that starts each mode's run, and what to call the run.
_STARTERS = {
    "deep": ("deep_research", "deep research run"),
    "factcheck": ("fact_check", "fact check"),
}


class RunClaimCheck(AgentMiddleware):
    """In a mode that starts a background run, a reply that ends the turn
    without starting one is sent back once to be checked.

    The prompt says a run exists only once its tool has started it, and the
    supervisor still told users "deep research is now running" without ever
    calling deep_research, twice in a handful of live runs. Whether to start a
    run stays the supervisor's call: this only makes sure the reply it sends
    is one it made with the fact in front of it. A greeting or a question back
    to the user costs one more model call, which the interface shows as a
    fresh attempt at the reply.
    """

    def __init__(self, mode: str) -> None:
        super().__init__()
        self.tool, self.run = _STARTERS[mode]
        self.checked = False

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state, runtime) -> dict[str, Any] | None:
        messages = state["messages"]
        if self.checked or not messages or getattr(messages[-1], "tool_calls", None):
            return None
        turn = []
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                break
            turn.append(message)
        # Steering a run that is already going is acting on it too.
        acted = {self.tool, "steer_deep_research"}
        if any(getattr(m, "name", None) in acted for m in turn):
            return None
        self.checked = True
        return {
            "jump_to": "model",
            "messages": [
                HumanMessage(
                    f"(A check from Nexus, not from the user.) No {self.run} has "
                    f"been started in this turn: {self.tool} was not called. If "
                    "your reply says one is starting, running or underway, it is "
                    f"not, so call {self.tool} now. If you meant to reply without "
                    "starting one, send the same reply again, unchanged: the "
                    "user has not seen it yet, so it is not waiting on them."
                )
            ],
        }


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
    start_deep_research: Callable[[str, str, str], Awaitable[str]] | None,
    start_fact_check: Callable[[int, str, str], Awaitable[str]] | None,
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

    async def deep_research(question: str, title: str, goal: str) -> str:
        if start_deep_research is None:
            return "Deep research is not available here. Use research instead."
        return await start_deep_research(question, title, goal)

    async def fact_check(document_id: int, title: str, focus: str = "") -> str:
        if start_fact_check is None:
            return "Fact-checking is not available here."
        if document_id not in by_id:
            known = ", ".join(str(i) for i in by_id) or "none"
            return f"No document with id {document_id}. Attached ids: {known}."
        return await start_fact_check(document_id, title, focus)

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
                    "Start a deep research run: deeper than research, several "
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


def _answer(text: str, sources: Sources) -> Answer:
    """The reply as the user sees it: invented citations dropped, and only the
    sources it really cites kept."""
    if not text.strip():
        logger.warning("the supervisor produced no reply")
        return Answer(text="", sources=[])
    # keep_uncited=False: an answer that cites nothing should not drag a source
    # list behind it, unlike a report, whose sources are half the point.
    content, cited, stripped = finalize(text, sources.all, keep_uncited=False)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
    return Answer(text=content.strip(), sources=cited)
