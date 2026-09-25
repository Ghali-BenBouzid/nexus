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
from typing import Annotated

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
    ToolMessage,
)
from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import BaseModel, Field

from app.agents.citations import finalize
from app.agents.claim_check import STARTERS, RunClaimCheck, claim_judge
from app.agents.language import detect_language
from app.agents.model import REASONING, STAGE_KEY, LastStep
from app.agents.report import text_of
from app.agents.research import Limits, Middleware, render_findings, run_research
from app.agents.research import tagged as tagged_emit
from app.agents.schemas import AgentEvent, ResearchResult, Source, Turn
from app.agents.sources import Sources
from app.agents.titles import StepTitles, step_titles
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
class Running:
    """A background run still working in this conversation. ``kind`` is the
    mode that starts it ("deep" or "factcheck"); ``stage`` says how far along
    it is, in words the supervisor can pass on."""

    id: int
    kind: str
    title: str
    stage: str


@dataclass
class Answer:
    """What one turn produced: the reply as the user sees it and the sources it
    cites."""

    text: str
    sources: list[Source] = field(default_factory=list)
    # The questions the turn ended on, when it called ask_user: each a dict of
    # question and options, as the user's panel shows them.
    ask: list[dict] | None = None


class ResearchArgs(BaseModel):
    question: str = Field(
        description="A clear, self-contained research question, in the user's "
        "language, carrying the context researchers need"
    )
    # Filled in by LangChain, never by the model: it is left out of the schema
    # the model sees. It names the team in the feed, because two research calls
    # can run at once and their researchers are both numbered from 1.
    tool_call_id: Annotated[str, InjectedToolCallId]


class DeepBrief(BaseModel):
    """What the user and the supervisor agreed a deep run is for, in the
    brainstorm before it. Everything but the goal can be empty: a field the
    user never touched is left out, not guessed."""

    goal: str = Field(
        description="What the user wants the report for and why, as a concrete "
        "goal: 'choose a specialisation to train for next year', not 'learning'"
    )
    reader: str = Field(
        default="", description="Who reads the report and what they already know"
    )
    focus: list[str] = Field(
        default_factory=list, description="The areas to cover, most important first"
    )
    open: list[str] = Field(
        default_factory=list,
        description="What the user left open, for the research to settle",
    )
    decided: list[str] = Field(
        default_factory=list,
        description="What the user left to you with 'Decide for me', and what "
        "you chose",
    )
    out_of_scope: list[str] = Field(
        default_factory=list, description="What to leave out"
    )
    constraints: str = Field(
        default="", description="Region, timeframe, budget, the language of sources"
    )
    shape: str = Field(
        default="",
        description="The kind of report: a comparison, a recommendation, a "
        "primer, or what the user asked for",
    )


_BRIEF_LINES = (
    ("goal", "Goal"),
    ("reader", "Reader"),
    ("focus", "Focus, most important first"),
    ("open", "Left open, for the research to settle"),
    ("decided", "Left to you, and what was chosen"),
    ("out_of_scope", "Out of scope"),
    ("constraints", "Constraints"),
    ("shape", "Shape of the report"),
)


def render_brief(brief: DeepBrief) -> str:
    """The brief as the lead reads it, under the question: one labelled line
    per field the brainstorm filled, and nothing for the ones it did not."""
    lines = ["The brief, agreed with the user before the run:"]
    for name, label in _BRIEF_LINES:
        value = getattr(brief, name)
        text = "; ".join(value) if isinstance(value, list) else value
        if text.strip():
            lines.append(f"- {label}: {text.strip()}")
    return "\n".join(lines)


class DeepResearchArgs(BaseModel):
    question: str = Field(
        description="The user's question, self-contained and in their language, "
        "as they would ask it: not a syllabus or a list of topics to cover"
    )
    brief: DeepBrief = Field(
        description="The brief agreed in the brainstorm, in the user's language"
    )
    title: str = Field(
        description="A short title, a few words in the user's language, naming "
        "the report this will produce"
    )


class AskQuestion(BaseModel):
    question: str = Field(description="One short question, in the user's language")
    options: list[str] = Field(
        min_length=2,
        max_length=4,
        description="2 to 4 short answers built from this conversation, each a "
        "few words. The interface adds 'Something else' and Skip itself: never "
        "write those.",
    )


class AskUserArgs(BaseModel):
    questions: list[AskQuestion] = Field(
        min_length=1,
        max_length=4,
        description="1 to 4 questions, shown one after the other in one panel",
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
    running: list[Running] | None = None,
    steer_deep_research: Callable[[int, str], Awaitable[str]] | None = None,
) -> Answer:
    """Answer the latest message, doing whatever work that needs first.

    ``history`` is the conversation before it, one entry per turn. The two
    ``start_*`` callbacks queue a background run and return what to tell the
    user; leaving one out simply removes that tool. ``on_research`` hands each
    research run's full result to a caller that wants to look inside it: the
    eval harness, which cannot otherwise see what happened behind a tool call.

    A deep run starts only from deep mode: outside it the tool does not exist,
    because a ten-minute run is the user's call to make, not the supervisor's.
    """
    documents = documents or []
    outputs = outputs or []
    running = running or []
    if mode != "deep":
        start_deep_research = None
    asked: list[dict] = []
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
            _ask_tool(asked),
        ],
        system_prompt=_system_prompt(
            message, documents, outputs, mode=mode, running=running
        ),
        middleware=[
            *middleware("supervisor", emit),
            EndOnAsk(),
            # Out of rounds means answer with what it has, not fail the turn,
            # and it is told so on the last one rather than cut off.
            LastStep(
                max_iters,
                "This is your last step: no more tool calls after it. Answer the "
                "user now with what you have, and say plainly what you could not "
                "finish.",
            ),
            *_claim_check(mode, model, running),
            ModelCallLimitMiddleware(run_limit=max_iters, exit_behavior="end"),
        ],
    )
    titles = step_titles(model, emit, detect_language(message))
    state = await _stream(agent, _conversation(history, message), emit, titles)
    answer = _answer(_last_text(state.get("messages", [])), sources)
    answer.ask = asked or None
    return answer


# The supervisor's own stage. A sub-agent called through a tool runs under its
# own stage, so this is what separates the supervisor's thinking from a
# researcher's: both run create_agent graphs whose model node is called "model",
# and their chunks would otherwise interleave into the user's reply.
_OWN_STAGE = "supervisor"


async def _stream(
    agent, messages: list[BaseMessage], emit: Emit, titles: StepTitles | None = None
) -> dict:
    """Run the agent, emitting its reply as it is written and naming its thinking.

    Two stream modes at once: ``messages`` for the chunks, ``values`` for the
    state we return, which is the same state ``ainvoke`` would have given us.
    The caller is unchanged; only the timing of what the user sees is.

    The thinking itself is not sent anywhere: the feed shows a short title for
    each stretch of it (app.agents.titles), never the scratchpad.
    """
    state: dict = {}
    try:
        async for mode, payload in agent.astream(
            {"messages": messages}, stream_mode=["messages", "values"]
        ):
            if mode == "values":
                state = payload
                continue
            chunk, _ = payload
            # Two things are not the answer being written. A tool's result, which
            # this stream carries alongside the model's own chunks; and a
            # sub-agent's chunks, which look identical because a sub-agent is a
            # create_agent graph too, with a model node called "model" just the same.
            if not isinstance(chunk, AIMessageChunk):
                continue
            extra = chunk.additional_kwargs or {}
            if extra.get(STAGE_KEY, _OWN_STAGE) != _OWN_STAGE:
                continue
            thought = extra.get(REASONING)
            if thought:
                if titles is not None:
                    await titles.think(chunk.id, thought)
                continue
            # Anything else the model sends ends its thinking: a word of the
            # reply, or the tool call the thinking was leading up to.
            if titles is not None:
                await titles.end()
            if chunk.text:
                await emit(AgentEvent(type="token", message=chunk.text))
    except BaseException:
        # Stopped or failed: nobody is waiting for the titles still on their way.
        if titles is not None:
            titles.cancel()
        raise
    if titles is not None:
        await titles.close()
    return state


def _system_prompt(
    message: str,
    documents: list[Document],
    outputs: list[Output],
    *,
    mode: str = "answer",
    running: list[Running] | None = None,
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


_KINDS = {"deep": "deep research", "factcheck": "fact check"}


def _running(running: list[Running]) -> str:
    """The background runs still working in this conversation. Without this the
    supervisor could not tell a run was going at all, and a user changing
    their mind got a second run, or a promise that the first had changed."""
    lines = [f"- {_KINDS[r.kind]}, id {r.id}: {r.title} ({r.stage})" for r in running]
    text = (
        "<running>\nBackground runs still working in this conversation, not "
        "readable yet:\n" + "\n".join(lines) + "\nThese are already running: "
        "saying so is true, and none of them needs starting again."
    )
    if any(r.kind == "deep" for r in running):
        text += (
            " When the user changes their mind about a deep research run, corrects "
            "an assumption it was started with, or wants its focus changed, pass "
            "that to it with steer_deep_research instead of starting another run. "
            "Only one deep research run works at a time in a conversation. Say "
            "what the tool says will happen, nothing more."
        )
    return text + "\n</running>"


ASKED = "Shown to the user. Stop here: their answer arrives as their next message."


def _ask_tool(asked: list[dict]) -> StructuredTool:
    """ask_user: questions with options, shown in a panel above the composer.

    It ends the turn: nothing is waiting for an answer, which
    comes back as the user's next message like anything else they say. What it
    asked lands in ``asked``, for the turn to store with its reply. EndOnAsk
    is what ends the turn."""

    async def ask_user(questions: list[AskQuestion]) -> str:
        asked[:] = [q.model_dump() for q in questions]
        return ASKED

    return StructuredTool.from_function(
        coroutine=ask_user,
        name="ask_user",
        description=(
            "Ask the user one to four questions, each with two to four short "
            "options they answer with one click, shown one after the other in a "
            "panel under your reply. Write your reply first, in the same message, "
            "then call this alone, as the last thing in your turn: the turn ends "
            "here, and their answers come back as their next message. For real "
            "choices only, never to ask whether they want you to go on."
        ),
        args_schema=AskUserArgs,
    )


class EndOnAsk(AgentMiddleware):
    """Ends the turn once ask_user has shown its questions.

    Not return_direct: that ends the turn on the tool's error too, and a
    question sent with one option would reach nobody. A call that failed its
    schema goes back to the model to be fixed, like any other tool's."""

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict | None:
        return {"jump_to": "end"} if _asked(state["messages"]) else None


def _asked(messages: list) -> AIMessage | None:
    """The step that asked, when the latest tool results include a successful
    ask_user; it can share its step with another tool."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, ToolMessage):
            break
        if message.name == "ask_user" and message.status != "error":
            return next(
                (m for m in reversed(messages[:index]) if isinstance(m, AIMessage)),
                None,
            )
    return None


def _steer_tool(
    running: list[Running],
    steer: Callable[[int, str], Awaitable[str]] | None,
) -> list[StructuredTool]:
    if steer is None or not any(r.kind == "deep" for r in running):
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
worth researching in depth, agree its brief with them, then start \
deep_research on it, with a short title that names the subject. Do not answer \
it with a quick research pass instead, and do not judge it too small for a \
deep run: choosing this mode is the user asking for depth, and that call is \
theirs. research and web_search stay for what is not the run itself: a side \
question while a run works, or what you need to ask them good questions.

<brainstorm>
A deep run takes several minutes and is only as good as its brief, so before \
starting one you agree the brief with the user in a short brainstorm, through \
ask_user. How much there is to ask depends on what they already said: never \
ask what the conversation already answers.

It is three steps by default:
1. The goal: what they want the report for, as concrete goals for this \
subject to choose from (choose a specialisation to train for, compare two \
offers before signing one, prepare a talk). Skip it when the conversation \
already makes the goal clear.
2. What that goal needs: two to four questions in one panel, chosen from the \
goal, and only on what would change what gets researched: who reads the report \
and what they already know; which areas matter most; depth on a few areas or \
a broad first look; constraints such as region, timeframe or budget; the shape \
of the report (a comparison, a recommendation, a primer).
3. The confirmation: two or three sentences restating the brief in your own \
words, then one question asking whether to launch the run, with an option to \
launch it and one to change something.
Add a panel only when an answer opens a real fork, one that changes what the \
run should research. When the user changes their mind at any point, go back to \
whatever it touches and carry on from there. Start deep_research only once \
they have confirmed; if they tell you to just go, restate the brief in a line \
and start.

When their message asks something you can answer now, answer it briefly \
before the first panel: the brainstorm shapes the report, it is not a reason \
to leave a question unanswered. Keep that answer short; the report is where \
the depth goes.

What makes a good question:
- Build every option from this subject and this conversation. "For a \
decision" or "to learn" are not options; "pick between LangGraph and \
LlamaIndex for a RAG job" is.
- For the areas to cover, think of the people who care about this subject and \
what each would want answered (for a job market question: a recruiter, a \
hiring manager, someone changing careers), and offer the angles they point to.
- Options are a few words each, distinct, and never overlap.
- End every question with a "Decide for me" option, in the user's language. \
When they choose it, decide what serves their goal best and say what you chose \
in the confirmation.
- When you do not know the subject well enough to ask good questions, search \
first with web_search, then ask. These searches are for your questions: no \
citations and no summary of what you found.

Pass everything in the brief argument: the goal as what they want and why, the \
reader, the areas to focus on in order, what they left open, what they left to \
you and what you chose, what is out of scope, the constraints, and the shape \
of the report. Keep the question the user's own question rather than a list \
of topics.
</brainstorm>

When this message is not something to research (a greeting, small talk, a \
question about Nexus, or a request not to research), do not start a run. \
Answer it as you normally would, and say in a sentence what deep research is \
for and what to send to start one.
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


def _claim_check(mode: str, model: BaseChatModel, running: list[Running]) -> list:
    """The check on a reply claiming a run nobody started, in a mode that
    starts one; none when the small model that runs it is switched off."""
    judge = claim_judge(model) if mode in STARTERS else None
    if judge is None:
        return []
    return [RunClaimCheck(mode, judge, [r.title for r in running if r.kind == mode])]


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
        HumanMessage(turn.content)
        if turn.role == "user"
        else AIMessage(_with_questions(turn.content, turn.ask))
        for turn in history
    ]
    messages.append(HumanMessage(message))
    return messages


def _with_questions(text: str, ask: list[dict] | None) -> str:
    """An earlier reply as the model reads it back: its text, then any
    questions it ended on with their options numbered, as the user saw them,
    so a typed "2" is read against the right question."""
    if not ask:
        return text
    lines = ["(You asked, with these options:)"]
    for number, question in enumerate(ask, start=1):
        lines.append(f"{number}. {question['question']}")
        options = "  ".join(
            f"{i}) {option}" for i, option in enumerate(question["options"], start=1)
        )
        lines.append(f"   {options}")
    return "\n\n".join(part for part in (text, "\n".join(lines)) if part)


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
        await emit(
            AgentEvent(
                type="document_read",
                message=f"Reading {output.title}",
                data={"agent": "supervisor", "document": output.title},
            )
        )
        return tagged("report", output.content, title=output.title)

    async def research(question: str, tool_call_id: str) -> str:
        result = await run_research(
            question,
            model=model,
            backend=backend,
            sources=sources,
            emit=tagged_emit(emit, team=tool_call_id),
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

    async def deep_research(question: str, title: str, brief: DeepBrief) -> str:
        if start_deep_research is None:
            return "Deep research is not available here. Use research instead."
        return await start_deep_research(question, title, render_brief(brief))

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
    """The reply: the last thing the agent wrote that was not a tool call, or,
    on a turn that ended by asking, what it wrote alongside the question."""
    step = _asked(messages)
    if step is not None:
        return text_of(step)
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
