import logging
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.agents.orchestrator import PriorReport
from app.agents.provider import LLMProvider
from app.agents.schemas import Turn
from app.agents.tools import SearchBackend, tagged
from app.billing.metering import MeteredProvider
from app.conversations import repository
from app.db import session as db_session
from app.models.conversation import Conversation, Message, MessageRole
from app.models.query import Query, QueryStatus
from app.research import repository as research_repository
from app.research import service as research_service
from app.research.dependencies import get_provider, get_search_backend

logger = logging.getLogger(__name__)

# Keep the context the supervisor sees bounded: only the tail of the thread, and
# each report trimmed, so routing stays a cheap call. The supervisor can pull the
# full text of any report on demand via its read_reports tool.
_MAX_CONTEXT_MESSAGES = 8
_MAX_REPORT_CHARS = 1200


def _history(messages: list[Message], queries: dict[int, Query]) -> list[Turn]:
    """The tail of the thread as turns, one per message. A turn that produced a
    report carries it shortened inside a <report> tag: retrieved material the
    supervisor must not mistake for the user's instructions, and whose full text
    it can pull with read_reports."""
    turns: list[Turn] = []
    for message in messages[-_MAX_CONTEXT_MESSAGES:]:
        if message.role == MessageRole.user:
            if message.content:
                turns.append(Turn(role="user", content=message.content))
            continue
        query = queries.get(message.query_id) if message.query_id else None
        if query is not None and query.report:
            excerpt = query.report[:_MAX_REPORT_CHARS]
            if len(query.report) > _MAX_REPORT_CHARS:
                excerpt += "\n[...excerpt; call read_reports for the full text]"
            turns.append(
                Turn(
                    role="assistant",
                    content=tagged("report", excerpt, question=query.prompt),
                )
            )
        elif message.content:
            turns.append(Turn(role="assistant", content=message.content))
    return turns


async def submit_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    background_tasks: BackgroundTasks,
) -> Message:
    """Record the user's message and the assistant turn that will answer it, and
    queue the routing job; no model is called in the request. The turn's query
    tracks it from here: its events feed the live progress bar, and it ends
    complete (a reply or a report), awaiting_plan or failed. Returns the
    assistant message. The caller checks the account's budget first."""
    await repository.add_message(db, conversation.id, MessageRole.user, content)
    query = await research_repository.create_pending_query(
        db=db, user_id=conversation.user_id, prompt=content
    )
    assistant = await repository.add_message(
        db, conversation.id, MessageRole.assistant, content="", query_id=query.id
    )
    await jobs.submit(
        background_tasks,
        route_message,
        provider=provider,
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
    provider: LLMProvider | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """The job for a new message: runs the research graph from the supervisor,
    which answers from the conversation, composes its reports into a longer one,
    or plans research and pauses for the user to review the plan. Every model call
    is billed to the conversation's owner."""
    async with db_session.SessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        query = await db.get(Query, query_id)
        if conversation is None or query is None:
            return
        user_id = conversation.user_id
        untitled = not conversation.title

        # The thread before this turn; the user's message is the question itself.
        messages = await repository.list_messages(db, conversation_id)
        before = [m for m in messages if m.id < message_id]
        if before and before[-1].role == MessageRole.user:
            before = before[:-1]
        query_ids = [m.query_id for m in before if m.query_id is not None]
        queries = await repository.queries_by_id(db, query_ids)
        completed = [
            queries[m.query_id]
            for m in before
            if m.query_id in queries
            and queries[m.query_id].status == QueryStatus.complete
            and queries[m.query_id].report
        ]
        graph_input = {
            "message": query.prompt,
            "history": _history(before, queries),
            "prior": [
                PriorReport(prompt=q.prompt, report=q.report or "", result=q.result)
                for q in completed
            ],
        }

    async def on_route(db: AsyncSession, decision: dict[str, Any]) -> None:
        if decision["route"] == "answer":
            await repository.set_content(db, message_id, decision["reply"])
        elif untitled and decision["title"]:
            # The first report names the conversation. Later turns keep the
            # original title, so the sidebar label stays stable.
            await repository.set_title(db, conversation_id, decision["title"])

    await research_service.run_graph(
        query_id,
        graph_input,
        provider=MeteredProvider(
            provider or get_provider(), user_id=user_id, query_id=query_id
        ),
        backend=backend or get_search_backend(),
        on_route=on_route,
    )
