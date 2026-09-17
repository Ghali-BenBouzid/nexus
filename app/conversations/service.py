import logging

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app import jobs
from app.agents import supervisor
from app.agents.narration import ThinkingProvider
from app.agents.provider import LLMProvider, ProviderCreditsError, ProviderError
from app.agents.tools import SearchBackend
from app.billing.metering import MeteredProvider
from app.conversations import repository
from app.core.config import settings
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

PROVIDER_DOWN = "The model provider is not responding. Try again in a moment."


def _render_context(messages: list[Message], queries: dict[int, Query]) -> str:
    """Render the tail of the thread for the supervisor: prior messages and a
    trimmed view of each report (the full text is available via read_reports)."""
    if not messages:
        return "This is the start of the conversation."
    lines: list[str] = []
    for message in messages[-_MAX_CONTEXT_MESSAGES:]:
        if message.role == MessageRole.user:
            lines.append(f"User: {message.content}")
            continue
        query = queries.get(message.query_id) if message.query_id else None
        if query is not None and query.report:
            lines.append(
                f"Assistant (research report excerpt):\n"
                f"{query.report[:_MAX_REPORT_CHARS]}"
            )
        elif message.content:
            lines.append(f"Assistant: {message.content}")
    return "\n\n".join(lines)


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
    """The routing job. The supervisor decides what the message needs (answer
    from the conversation, compose the existing reports, or research), then the
    turn carries on in this same job. Every model call is billed to the
    conversation's owner, and each one shows as "thinking" on the turn."""
    provider = provider or get_provider()
    backend = backend or get_search_backend()
    async with db_session.SessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        query = await db.get(Query, query_id)
        if conversation is None or query is None:
            return
        user_id = conversation.user_id
        content = query.prompt

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

        emit = research_service.EventSink(query_id)
        metered = MeteredProvider(provider, user_id=user_id, query_id=query_id)
        async with research_service.job_liveness(query_id) as live:
            if not await research_repository.mark_running(db, query_id):
                return  # stopped while it waited in the queue
            try:
                async with metered, backend:
                    decision = await supervisor.decide(
                        content,
                        _render_context(before, queries),
                        provider=ThinkingProvider(metered, emit, agent="supervisor"),
                        backend=backend,
                        reports=[(q.prompt, q.report or "") for q in completed],
                        emit=emit,
                        max_iters=settings.supervisor_max_iters,
                    )
            except ProviderCreditsError as exc:
                await research_repository.fail_query(db, query_id, str(exc))
                return
            except ProviderError:
                await research_repository.fail_query(db, query_id, PROVIDER_DOWN)
                return
            except Exception:
                logger.exception("routing crashed for query %s", query_id)
                await research_repository.fail_query(
                    db, query_id, "Routing failed due to an internal error."
                )
                return
            if live.stopped:
                return

        if decision.action == "answer":
            await repository.set_content(db, message_id, decision.reply)
            await research_repository.complete_answer(db, query_id, decision.reply)
            return

        if decision.action == "compose" and completed:
            # Merge the existing reports into one new, longer report (no search).
            instructions = decision.instructions or content
            await research_repository.update_turn(
                db, query_id, prompt=instructions, title=decision.title or None
            )
            await _title_conversation(db, conversation, decision.title)
            await research_service.run_compose_job(
                query_id,
                instructions,
                source_query_ids=[q.id for q in completed],
                user_id=user_id,
                provider=provider,
            )
            return

        # research (the default, and the fallback when compose has nothing to
        # merge): plan now, then pause for the user to confirm the plan.
        research_query = decision.query or content
        await research_repository.update_turn(
            db, query_id, prompt=research_query, title=decision.title or None
        )
        await _title_conversation(db, conversation, decision.title)
        await research_service.run_plan_job(
            query_id, research_query, user_id=user_id, provider=provider
        )


async def _title_conversation(
    db: AsyncSession, conversation: Conversation, title: str
) -> None:
    """Name the conversation from its first report's title, once. Later turns keep
    the original title, so the sidebar label stays stable."""
    if title and not conversation.title:
        await repository.set_title(db, conversation.id, title)
