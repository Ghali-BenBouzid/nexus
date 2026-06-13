from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.provider import LLMProvider
from app.agents.tools import SearchBackend
from app.conversations import repository
from app.models.conversation import Conversation, Message, MessageRole
from app.research import repository as research_repository
from app.research import service as research_service


async def submit_message(
    db: AsyncSession,
    conversation: Conversation,
    content: str,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    background_tasks: BackgroundTasks,
) -> Message:
    """Record the user's message, start a research run for it, and create the
    assistant message that will carry the report. Returns the assistant message
    (its ``query_id`` is what the client polls). In step 3 this is where a
    supervisor decides whether to research, answer, or refine instead."""
    await repository.add_message(db, conversation.id, MessageRole.user, content)
    query = await research_repository.create_pending_query(
        db=db, user_id=conversation.user_id, prompt=content
    )
    assistant = await repository.add_message(
        db,
        conversation.id,
        MessageRole.assistant,
        content="",
        query_id=query.id,
    )
    background_tasks.add_task(
        research_service.run_research_job,
        query.id,
        content,
        provider=provider,
        backend=backend,
    )
    return assistant
