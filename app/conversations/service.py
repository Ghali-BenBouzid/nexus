from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import supervisor
from app.agents.provider import LLMProvider
from app.agents.tools import SearchBackend
from app.conversations import repository
from app.core.config import settings
from app.models.conversation import Conversation, Message, MessageRole
from app.models.query import Query, QueryStatus
from app.research import repository as research_repository
from app.research import service as research_service

# Keep the context the supervisor sees bounded: only the tail of the thread, and
# each report trimmed, so routing stays a cheap call. The supervisor can pull the
# full text of any report on demand via its read_reports tool.
_MAX_CONTEXT_MESSAGES = 8
_MAX_REPORT_CHARS = 1200

# Shown in the chat when a follow-up would start a research or compose run but the
# user has hit the daily cap. Answers from existing reports are not affected, so
# the conversation stays usable; only new heavy runs are held back.
_CAP_NOTICE = (
    "You have reached today's research limit. You can still ask about the "
    "reports already in this conversation. Please come back tomorrow for new runs."
)


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
    """Record the user's message and let the supervisor decide what to do: answer
    from the conversation's reports, compose a new report by merging the existing
    ones, or start a fresh research run. Returns the assistant message (its
    ``query_id`` is non-null when it carries a research or compose run)."""
    messages = await repository.list_messages(db, conversation.id)
    query_ids = [m.query_id for m in messages if m.query_id is not None]
    queries = await repository.queries_by_id(db, query_ids)
    context = _render_context(messages, queries)
    completed = [
        queries[m.query_id]
        for m in messages
        if m.query_id is not None
        and m.query_id in queries
        and queries[m.query_id].status == QueryStatus.complete
        and queries[m.query_id].report
    ]
    reports = [(query.prompt, query.report or "") for query in completed]

    await repository.add_message(db, conversation.id, MessageRole.user, content)

    # The supervisor runs a tool loop, so it needs both the provider (its own model
    # calls) and the search backend (its web_search / fetch_page tools) open.
    async with provider, backend:
        decision = await supervisor.decide(
            content,
            context,
            provider=provider,
            backend=backend,
            reports=reports,
            max_iters=settings.supervisor_max_iters,
        )

    if decision.action == "answer":
        return await repository.add_message(
            db, conversation.id, MessageRole.assistant, content=decision.reply
        )

    # Compose and research both launch a heavy job, so they draw on the daily cap.
    # Answers above are free (cheap, and they keep the chat usable once capped).
    if await research_service.over_daily_cap(db, conversation.user_id):
        return await repository.add_message(
            db, conversation.id, MessageRole.assistant, content=_CAP_NOTICE
        )

    if decision.action == "compose" and completed:
        # Merge the existing reports into one new, longer report (no new search).
        query = await research_repository.create_pending_query(
            db=db,
            user_id=conversation.user_id,
            prompt=decision.instructions or content,
            title=decision.title or None,
        )
        await _title_conversation(db, conversation, decision.title)
        assistant = await repository.add_message(
            db, conversation.id, MessageRole.assistant, content="", query_id=query.id
        )
        background_tasks.add_task(
            research_service.run_compose_job,
            query.id,
            decision.instructions or content,
            source_query_ids=[q.id for q in completed],
            provider=provider,
        )
        return assistant

    # research (the default, and the fallback when compose has nothing to merge):
    # plan first, then pause for the user to confirm the plan before research runs.
    research_query = decision.query or content
    query = await research_repository.create_pending_query(
        db=db,
        user_id=conversation.user_id,
        prompt=research_query,
        title=decision.title or None,
    )
    await _title_conversation(db, conversation, decision.title)
    assistant = await repository.add_message(
        db,
        conversation.id,
        MessageRole.assistant,
        content="",
        query_id=query.id,
    )
    background_tasks.add_task(
        research_service.run_plan_job,
        query.id,
        research_query,
        provider=provider,
    )
    return assistant


async def _title_conversation(
    db: AsyncSession, conversation: Conversation, title: str
) -> None:
    """Name the conversation from its first report's title, once. Later turns keep
    the original title, so the sidebar label stays stable."""
    if title and not conversation.title:
        await repository.set_title(db, conversation.id, title)
