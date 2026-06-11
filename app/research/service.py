import asyncio
import logging

from app.agents import orchestrator
from app.agents.orchestrator import OrchestratorError
from app.agents.planner import PlannerError
from app.agents.provider import LLMProvider
from app.agents.schemas import AgentEvent
from app.agents.tools import FetchPage, SearchBackend, WebSearch
from app.core.config import settings
from app.db import session as db_session
from app.models.query import QueryStatus
from app.research import repository

logger = logging.getLogger(__name__)


async def _log_emit(event: AgentEvent) -> None:
    # v1 sink: just log. Swapping this for an event-log/SSE feed is additive.
    logger.info("agent[%s] %s", event.type, event.message)


async def run_research_job(
    query_id: int,
    prompt: str,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
) -> None:
    """Background job for one query. Owns its own session (the request's closed
    when the 202 was sent), drives the orchestrator under a global timeout, and
    always resolves the status to complete or failed."""
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.running)
        try:
            async with provider, backend:
                tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
                report, research_result = await asyncio.wait_for(
                    orchestrator.run(
                        prompt,
                        provider=provider,
                        tools=tools,
                        emit=_log_emit,
                        cap=settings.cap,
                        max_iters=settings.max_iters,
                        max_concurrency=settings.max_concurrency,
                        per_researcher_timeout=settings.per_researcher_timeout,
                        retry_cap=settings.planner_retry_cap,
                    ),
                    timeout=settings.global_timeout,
                )
            await repository.complete_query(db, query_id, report, research_result)
        except TimeoutError:
            # global_timeout fired (asyncio.wait_for raises TimeoutError)
            logger.warning("research job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Research timed out.")
        except (PlannerError, OrchestratorError) as exc:
            # our own domain errors carry safe, user-meaningful messages
            logger.warning("research job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            # unknown/SDK errors may embed secrets: log full server-side, store generic
            logger.exception("research job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Research failed due to an internal error."
            )
