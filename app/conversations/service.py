from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import supervisor
from app.agents.provider import LLMProvider, ProviderCreditsError, ProviderError
from app.agents.tools import SearchBackend
from app.billing.metering import MeteredProvider
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
    """Let the supervisor decide what to do with the user's message: answer from
    the conversation's reports, compose a new report by merging the existing ones,
    or start a fresh research run. Records the user message and the assistant's,
    and returns the latter (its ``query_id`` is non-null when it carries a research
    or compose run). The caller checks the account's budget first.

    Every model call is billed to the conversation's owner through
    ``MeteredProvider``: the supervisor's own calls, and each job it launches."""
    user_id = conversation.user_id
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

    # The supervisor runs a tool loop, so it needs both the provider (its own model
    # calls) and the search backend (its web_search / fetch_page tools) open.
    metered = MeteredProvider(provider, user_id=user_id)
    try:
        async with metered, backend:
            decision = await supervisor.decide(
                content,
                context,
                provider=metered,
                backend=backend,
                reports=reports,
                max_iters=settings.supervisor_max_iters,
            )
    except ProviderCreditsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=PROVIDER_DOWN) from exc

    # Stored only once the supervisor has decided, so a provider failure above does
    # not leave an unanswered message in the thread.
    await repository.add_message(db, conversation.id, MessageRole.user, content)

    if decision.action == "answer":
        return await repository.add_message(
            db, conversation.id, MessageRole.assistant, content=decision.reply
        )

    if decision.action == "compose" and completed:
        # Merge the existing reports into one new, longer report (no new search).
        query = await research_repository.create_pending_query(
            db=db,
            user_id=user_id,
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
            provider=MeteredProvider(provider, user_id=user_id, query_id=query.id),
        )
        return assistant

    # research (the default, and the fallback when compose has nothing to merge):
    # plan first, then pause for the user to confirm the plan before research runs.
    research_query = decision.query or content
    query = await research_repository.create_pending_query(
        db=db,
        user_id=user_id,
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
        provider=MeteredProvider(provider, user_id=user_id, query_id=query.id),
    )
    return assistant


async def _title_conversation(
    db: AsyncSession, conversation: Conversation, title: str
) -> None:
    """Name the conversation from its first report's title, once. Later turns keep
    the original title, so the sidebar label stays stable."""
    if title and not conversation.title:
        await repository.set_title(db, conversation.id, title)
