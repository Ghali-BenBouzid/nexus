"""A turn of a conversation: the user's message in, the supervisor's answer out.

The turn itself is one job. What makes it more than a model call is what the
supervisor can reach from inside it: the documents attached to the thread, the
reports it has already produced, and two tools that start their own background
runs. Those two are wired here, because starting a run means writing a row and
queueing a job, which is the application's business and not the agent's.
"""

import logging

from fastapi import BackgroundTasks
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.agents.schemas import AgentEvent, ResearchResult, Turn
from app.agents.supervisor import Document, Output, Running, respond
from app.agents.tools import SearchBackend
from app.billing.service import has_budget
from app.conversations import repository
from app.conversations.schemas import Mode
from app.core.config import settings
from app.db import session as db_session
from app.documents import repository as documents_repository
from app.models.conversation import Conversation, Message, MessageRole
from app.models.query import Query, QueryKind, QueryStatus
from app.research import repository as research_repository
from app.research.deep import run_deep_research_job
from app.research.factcheck import run_fact_check_job
from app.research.service import Run, run_query

logger = logging.getLogger(__name__)

# The tail of the thread the supervisor sees. Older turns are not carried: what
# matters from them is in the reports and documents it can read on demand.
_MAX_CONTEXT_MESSAGES = 12
# A conversation is named from its first message rather than by a model. A title
# is a sidebar label, and paying for a call to write one is not worth it.
_TITLE_CHARS = 60

DEEP_STARTED = (
    "Deep research has started on that. It takes several minutes and will appear "
    "in the user's Outputs when it is done. Tell them it is running; do not wait "
    "for it or make up what it will say."
)
DEEP_BUSY = (
    "Nothing was started: deep research run {id} ({title}) is still working in "
    "this conversation, and only one works at a time. If the user wants its "
    "direction changed, pass that on with steer_deep_research; otherwise tell "
    "them a new run can start once this one is done."
)
FACT_CHECK_BUSY = (
    "Nothing was started: {filename} is already being checked in this "
    "conversation (fact check {id}, {title}). Its report will appear in Outputs "
    "when it is done; tell the user that rather than starting another."
)
FACT_CHECK_STARTED = (
    "The fact check has started on {filename}. Its report will appear in the "
    "user's Outputs when it is done. Tell them it is running; do not wait for it "
    "or make up its verdicts."
)
NO_BUDGET = (
    "There is not enough budget left on this account to start that run. Tell the "
    "user plainly."
)


def title_for(message: str) -> str:
    """A conversation's sidebar label, from its first message."""
    line = " ".join(message.split())
    if len(line) <= _TITLE_CHARS:
        return line
    return line[:_TITLE_CHARS].rsplit(" ", 1)[0] + "..."


def _history(messages: list[Message]) -> list[Turn]:
    """The tail of the thread as turns, one per message."""
    return [
        Turn(
            role="user" if m.role == MessageRole.user else "assistant",
            content=m.content,
        )
        for m in messages[-_MAX_CONTEXT_MESSAGES:]
        if m.content
    ]


async def submit_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    background_tasks: BackgroundTasks,
    document_ids: list[int] | None = None,
    mode: Mode = "answer",
) -> Message:
    """Record the user's message and the assistant turn that will answer it, and
    queue the job; no model is called in the request. The turn's query tracks it
    from here: its events feed the live progress, and it ends complete or failed.
    The caller checks the account's budget first.

    ``mode`` says what the user switched the composer to. It never starts a run
    itself: it tells the supervisor, which decides what this message calls for.
    A mode that fired on anything the user typed started ten-minute runs on "hi"
    and on "don't start a deep research"; judging the message is exactly what
    the supervisor is for, and the thread stays the supervisor's either way.
    """
    user_message = await repository.add_message(
        db, conversation.id, MessageRole.user, content
    )
    # The files were uploaded before the message, because a file belongs to a
    # conversation; this is what ties them to the message they were sent with.
    await documents_repository.attach_to_message(
        db,
        document_ids or [],
        message_id=user_message.id,
        user_id=conversation.user_id,
    )
    # What the supervisor is handed as the message. Usually what the user
    # typed; for a file sent on its own, a plain note of what arrived, so the
    # supervisor decides what the file is for rather than facing an empty turn.
    # The stored message stays empty, and the thread shows the file alone.
    prompt, title = content, content
    if not content.strip():
        names = ", ".join(
            d.filename
            for d in await documents_repository.list_for_conversation(
                db, conversation.id
            )
            if d.message_id == user_message.id
        )
        prompt = f"(Sent without a message: {names})"
        # The sidebar names a chat after what it is about, which is the file.
        title = names
    if not conversation.title:
        await repository.set_title(db, conversation.id, title_for(title))
    query = await research_repository.create_pending_query(
        db=db,
        user_id=conversation.user_id,
        prompt=prompt,
        kind=QueryKind.chat,
        conversation_id=conversation.id,
    )
    assistant = await repository.add_message(
        db, conversation.id, MessageRole.assistant, content="", query_id=query.id
    )
    await jobs.submit(
        background_tasks,
        route_message,
        model=model,
        backend=backend,
        query_id=query.id,
        conversation_id=conversation.id,
        message_id=assistant.id,
        mode=mode,
    )
    return assistant


async def route_message(
    query_id: int,
    conversation_id: int,
    message_id: int,
    *,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
    mode: Mode = "answer",
) -> None:
    """The job for a new message: the supervisor answers it, using whatever
    tools the answer needs. Every model call is billed to the thread's owner."""
    async with db_session.SessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        query = await db.get(Query, query_id)
        if conversation is None or query is None:
            return
        user_id = conversation.user_id
        message = query.prompt

        messages = await repository.list_messages(db, conversation_id)
        before = [m for m in messages if m.id < message_id]
        if before and before[-1].role == MessageRole.user:
            before = before[:-1]  # the user's message is the question itself
        history = _history(before)
        documents = [
            Document(id=d.id, filename=d.filename, text=d.text)
            for d in await documents_repository.list_for_conversation(
                db, conversation_id
            )
        ]
        outputs = [
            Output(id=q.id, title=q.title or q.prompt, content=q.report or "")
            for q in await research_repository.list_conversation_reports(
                db, conversation_id
            )
        ]
        running = [
            Running(
                id=q.id,
                kind=_MODE_OF[q.kind],
                title=q.title or q.prompt,
                stage=await _stage(db, q),
            )
            for q in await _working(db, conversation_id)
        ]

    async def work(run: Run) -> None:
        answer = await respond(
            message,
            history,
            model=run.model,
            backend=run.backend,
            sources=run.sources,
            documents=documents,
            outputs=outputs,
            start_deep_research=_deep_starter(run, conversation_id),
            start_fact_check=_fact_check_starter(run, conversation_id, documents),
            middleware=run.middleware,
            emit=run.emit,
            max_iters=settings.supervisor_max_iters,
            mode=mode,
            running=running,
            steer_deep_research=_steerer(conversation_id),
        )
        result = ResearchResult(
            points=[],
            sources=answer.sources,
            gaps=[],
            consulted_sources=list(run.sources.all),
        )
        async with db_session.SessionLocal() as db:
            await research_repository.complete_answer(
                db,
                query_id,
                answer.text,
                result=result,
            )
            await repository.set_content(db, message_id, answer.text)

    await run_query(query_id, user_id=user_id, work=work, model=model, backend=backend)


_MODE_OF = {QueryKind.deep_research: "deep", QueryKind.fact_check: "factcheck"}


async def _working(db: AsyncSession, conversation_id: int) -> list[Query]:
    """The background runs of a conversation still queued or working."""
    return [
        q
        for q in await research_repository.list_conversation_artifacts(
            db, conversation_id
        )
        if q.status in (QueryStatus.pending, QueryStatus.running)
    ]


async def _writing(db: AsyncSession, run_id: int) -> bool:
    """Whether a deep run has finished researching and is writing its report."""
    events = await research_repository.list_events(db, run_id, 0)
    return any(e.type in ("lead_done", "writer_start") for e in events)


async def _stage(db: AsyncSession, query: Query) -> str:
    if query.status == QueryStatus.pending:
        return "queued"
    if query.kind == QueryKind.deep_research and await _writing(db, query.id):
        return "writing its report"
    return "working"


def _deep_starter(run: Run, conversation_id: int):
    """The supervisor's deep_research tool: write the run's row, queue it, and
    hand back what to tell the user. The tool returns at once, because the point
    of a deep run is that nobody sits and waits for it."""

    async def start(question: str, title: str, goal: str) -> str:
        # One deep run per conversation, held here rather than asked of the
        # model: a supervisor misled once already started a copy of a run
        # that was still going.
        async with db_session.SessionLocal() as db:
            busy = [
                q
                for q in await _working(db, conversation_id)
                if q.kind == QueryKind.deep_research
            ]
        if busy:
            return DEEP_BUSY.format(id=busy[0].id, title=busy[0].title)
        # The goal travels with the question: the lead reads it to decide how
        # deep to go, and a resumed run reads it back off the row.
        prompt = f"{question}\n\nWhat it is for: {goal}" if goal.strip() else question
        query_id = await _start_run(
            run,
            conversation_id,
            kind=QueryKind.deep_research,
            prompt=prompt,
            title=title or question,
        )
        if query_id is None:
            return NO_BUDGET
        await jobs.spawn(run_deep_research_job, query_id=query_id)
        return DEEP_STARTED

    return start


def _fact_check_starter(run: Run, conversation_id: int, documents: list[Document]):
    by_id = {document.id: document for document in documents}

    async def start(document_id: int, title: str, focus: str) -> str:
        document = by_id.get(document_id)
        if document is None:
            return f"No document with id {document_id} is attached here."
        # One check of a document at a time, held here rather than asked of the
        # model: a supervisor that could not see the first check started a
        # second on "tell me jokes while I wait".
        async with db_session.SessionLocal() as db:
            busy = [
                q
                for q in await _working(db, conversation_id)
                if q.kind == QueryKind.fact_check and q.document_id == document_id
            ]
        if busy:
            return FACT_CHECK_BUSY.format(
                filename=document.filename, id=busy[0].id, title=busy[0].title
            )
        query_id = await _start_run(
            run,
            conversation_id,
            kind=QueryKind.fact_check,
            prompt=focus or document.filename,
            # Written by the supervisor, in the user's language: a title made
            # here was English in every conversation.
            title=title or document.filename,
            document_id=document_id,
        )
        if query_id is None:
            return NO_BUDGET
        await jobs.spawn(
            run_fact_check_job,
            query_id=query_id,
            document_id=document_id,
            focus=focus,
        )
        return FACT_CHECK_STARTED.format(filename=document.filename)

    return start


STEERED_NEXT = (
    "Noted on the run. Its lead reads the note before its next step, usually "
    "within a few minutes, and adjusts what it researches from there; what is "
    "already found stays in the report where it still applies. Tell the user "
    "that in a sentence. Do not claim the report has already changed."
)
STEERED_LATE = (
    "The run has finished researching and is writing its report. The note goes "
    "to the writer, who will frame the report by it where the findings allow, "
    "but nothing new will be researched for it. Tell the user that, and offer "
    "to start a new deep research run if the change needs new research."
)


def _steerer(conversation_id: int):
    """The supervisor's steer_deep_research tool: a note stored on a running
    deep run, which its lead reads before its next step. Checked here rather
    than trusted: the run has to belong to this conversation and still be
    working, and the reply says honestly how much the note can still change."""

    async def steer(run_id: int, note: str) -> str:
        if not note.strip():
            return "The note was empty. Pass what the user wants changed."
        async with db_session.SessionLocal() as db:
            query = await db.get(Query, run_id)
            if (
                query is None
                or query.conversation_id != conversation_id
                or query.kind != QueryKind.deep_research
            ):
                return (
                    f"No deep research run with id {run_id} belongs to this "
                    "conversation."
                )
            if query.status not in (QueryStatus.pending, QueryStatus.running):
                return (
                    f"Run {run_id} is no longer running ({query.status}), so it "
                    "cannot be changed. Offer to start a new run with the change."
                )
            writing = await _writing(db, run_id)
            await research_repository.add_event(
                db,
                run_id,
                AgentEvent(type=research_repository.STEERED, message=note.strip()),
            )
        return STEERED_LATE if writing else STEERED_NEXT

    return steer


async def _start_run(
    run: Run,
    conversation_id: int,
    *,
    kind: QueryKind,
    prompt: str,
    title: str,
    document_id: int | None = None,
) -> int | None:
    """Create the row a background run will report into, unless the account has
    nothing left to spend. Returns its id, or None when the budget is gone: a
    run nobody can pay for should never be queued."""
    async with db_session.SessionLocal() as db:
        if not await has_budget(db, run.user_id):
            return None
        query = await research_repository.create_pending_query(
            db=db,
            user_id=run.user_id,
            prompt=prompt,
            title=title,
            kind=kind,
            conversation_id=conversation_id,
            document_id=document_id,
        )
        return query.id
