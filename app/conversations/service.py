from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import supervisor
from app.agents.provider import LLMProvider
from app.agents.tools import SearchBackend
from app.conversations import repository
from app.models.conversation import Conversation, Message, MessageRole
from app.research import repository as research_repository
from app.research import service as research_service

# Keep the context the supervisor sees bounded: only the tail of the thread, and
# each report trimmed, so routing stays a cheap call.
_MAX_CONTEXT_MESSAGES = 8
_MAX_REPORT_CHARS = 2000


async def _render_context(db: AsyncSession, conversation_id: int) -> str:
    """Render the conversation so far for the supervisor: prior messages and the
    reports they produced. Bounded in length to keep the routing call cheap."""
    messages = await repository.list_messages(db, conversation_id)
    if not messages:
        return "This is the start of the conversation."
    messages = messages[-_MAX_CONTEXT_MESSAGES:]

    query_ids = [m.query_id for m in messages if m.query_id is not None]
    queries = await repository.queries_by_id(db, query_ids)

    lines: list[str] = []
    for message in messages:
        if message.role == MessageRole.user:
            lines.append(f"User: {message.content}")
            continue
        query = queries.get(message.query_id) if message.query_id else None
        if query is not None and query.report:
            lines.append(
                f"Assistant (research report):\n{query.report[:_MAX_REPORT_CHARS]}"
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
    from the conversation's reports, or start a fresh research run. Returns the
    assistant message (its ``query_id`` is non-null only when it carries research)."""
    context = await _render_context(db, conversation.id)
    await repository.add_message(db, conversation.id, MessageRole.user, content)

    async with provider:
        decision = await supervisor.decide(content, context, provider=provider)

    if decision.action == "answer":
        return await repository.add_message(
            db, conversation.id, MessageRole.assistant, content=decision.reply
        )

    query = await research_repository.create_pending_query(
        db=db, user_id=conversation.user_id, prompt=decision.query
    )
    assistant = await repository.add_message(
        db,
        conversation.id,
        MessageRole.assistant,
        content="",
        query_id=query.id,
    )
    # Human-in-the-loop: plan first, then pause for the user to confirm the plan
    # (POST /research/query/{id}/confirm) before the research runs. The backend is
    # picked up again by the confirm endpoint for phase 2.
    background_tasks.add_task(
        research_service.run_plan_job,
        query.id,
        decision.query,
        provider=provider,
    )
    return assistant
