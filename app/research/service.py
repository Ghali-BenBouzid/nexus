import asyncio
import logging

from app.agents import orchestrator
from app.agents.orchestrator import OrchestratorError
from app.agents.planner import PlannerError
from app.agents.provider import LLMProvider
from app.agents.schemas import AgentEvent
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import FetchPage, SearchBackend, WebSearch
from app.core.config import settings
from app.db import session as db_session
from app.models.query import QueryStatus
from app.research import repository

logger = logging.getLogger(__name__)


class _EventSink:
    """The emit sink: persists each agent event so a polling client can tail the
    live feed (``GET /research/query/{id}/events``).

    Each event is written in its own short-lived session — the job's own session
    is single-threaded and not safe for the concurrent emits a researcher fan-out
    produces, and a fresh session per event sidesteps that entirely. A feed write
    must never sink the run, so any failure here is logged and swallowed."""

    def __init__(self, query_id: int) -> None:
        self.query_id = query_id

    async def __call__(self, event: AgentEvent) -> None:
        logger.info("agent[%s] %s", event.type, event.message)
        try:
            async with db_session.SessionLocal() as db:
                await repository.add_event(db, self.query_id, event)
        except Exception:
            logger.exception(
                "failed to persist agent event for query %s", self.query_id
            )


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
            backend = CachingSearchBackend(backend)
            async with provider, backend:
                tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
                report, research_result = await asyncio.wait_for(
                    orchestrator.run(
                        prompt,
                        provider=provider,
                        tools=tools,
                        emit=_EventSink(query_id),
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
