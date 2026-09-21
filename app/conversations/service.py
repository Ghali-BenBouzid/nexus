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
from app.agents.schemas import ResearchResult, Turn
from app.agents.supervisor import Document, Output, respond
from app.agents.tools import SearchBackend
from app.billing.service import has_budget
from app.conversations import repository
from app.core.config import settings
from app.db import session as db_session
from app.documents import repository as documents_repository
from app.models.conversation import Conversation, Message, MessageRole
from app.models.query import Query, QueryKind
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
    deep: bool = False,
) -> Message:
    """Record the user's message and the assistant turn that will answer it, and
    queue the job; no model is called in the request. The turn's query tracks it
    from here: its events feed the live progress, and it ends complete or failed.
    The caller checks the account's budget first.

    ``deep`` makes the turn a deep research run instead of a supervisor answer.
    It is the same run the supervisor can start for itself, started by the user
    instead, and it is still one turn of this conversation: the report is what
    the turn produces, the way an answer is on any other turn.
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
    if not conversation.title:
        await repository.set_title(db, conversation.id, title_for(content))
    query = await research_repository.create_pending_query(
        db=db,
        user_id=conversation.user_id,
        prompt=content,
        kind=QueryKind.deep_research if deep else QueryKind.chat,
        title=title_for(content) if deep else None,
        conversation_id=conversation.id,
    )
    assistant = await repository.add_message(
        db, conversation.id, MessageRole.assistant, content="", query_id=query.id
    )
    if deep:
        # Always the worker, never this process: a deep run takes minutes, and
        # a BackgroundTask would hold a request handler open for all of them.
        await jobs.spawn(run_deep_research_job, query_id=query.id)
        return assistant
    await jobs.submit(
        background_tasks,
        route_message,
        model=model,
        backend=backend,
        query_id=query.id,
        conversation_id=conversation.id,
        message_id=assistant.id,
    )
    return assistant


async def route_message(
    query_id: int,
    conversation_id: int,
    message_id: int,
    *,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
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


def _deep_starter(run: Run, conversation_id: int):
    """The supervisor's deep_research tool: write the run's row, queue it, and
    hand back what to tell the user. The tool returns at once, because the point
    of a deep run is that nobody sits and waits for it."""

    async def start(question: str, title: str) -> str:
        query_id = await _start_run(
            run,
            conversation_id,
            kind=QueryKind.deep_research,
            prompt=question,
            title=title or question,
        )
        if query_id is None:
            return NO_BUDGET
        await jobs.spawn(run_deep_research_job, query_id=query_id)
        return DEEP_STARTED

    return start


def _fact_check_starter(run: Run, conversation_id: int, documents: list[Document]):
    by_id = {document.id: document for document in documents}

    async def start(document_id: int, focus: str) -> str:
        document = by_id.get(document_id)
        if document is None:
            return f"No document with id {document_id} is attached here."
        query_id = await _start_run(
            run,
            conversation_id,
            kind=QueryKind.fact_check,
            prompt=focus or f"Fact check of {document.filename}",
            title=f"Fact check: {document.filename}",
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


async def _start_run(
    run: Run,
    conversation_id: int,
    *,
    kind: QueryKind,
    prompt: str,
    title: str,
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
        )
        return query.id
