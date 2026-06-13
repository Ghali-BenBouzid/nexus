import asyncio
import logging

from app.agents import orchestrator
from app.agents.orchestrator import OrchestratorCancelledError, OrchestratorError
from app.agents.planner import PlannerError, plan
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


# Query ids the user has asked to stop. The job polls this (cooperatively) and
# aborts; in-process is enough because the job runs in this same process (a real
# task queue would move this to Redis/DB). Membership is cleared when the job ends.
_cancel_requested: set[int] = set()


def request_cancel(query_id: int) -> None:
    _cancel_requested.add(query_id)


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
                        should_cancel=lambda: query_id in _cancel_requested,
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
        except OrchestratorCancelledError:
            logger.info("research job %s stopped by the user", query_id)
            await repository.fail_query(db, query_id, "Research was stopped.")
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
        finally:
            _cancel_requested.discard(query_id)


async def run_plan_job(
    query_id: int,
    prompt: str,
    *,
    provider: LLMProvider,
    feedback: str | None = None,
) -> None:
    """Phase 1 of a human-in-the-loop run: plan only, then pause for the user to
    confirm or revise (``status=awaiting_plan``). ``feedback`` re-plans after a
    rejection. A planner failure resolves the status to failed."""
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.running)
        try:
            async with provider:
                sub_questions = await plan(
                    prompt,
                    provider=provider,
                    emit=_EventSink(query_id),
                    cap=settings.cap,
                    retry_cap=settings.planner_retry_cap,
                    feedback=feedback,
                )
            await repository.set_plan(db, query_id, sub_questions)
        except PlannerError as exc:
            logger.warning("plan job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            logger.exception("plan job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Planning failed due to an internal error."
            )


async def run_research_from_plan_job(
    query_id: int,
    sub_questions: list[str],
    *,
    provider: LLMProvider,
    backend: SearchBackend,
) -> None:
    """Phase 2: execute a confirmed plan (research -> consolidate -> write). Same
    resolution + hang-safety as the one-shot job, minus the planning."""
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.running)
        try:
            backend = CachingSearchBackend(backend)
            async with provider, backend:
                tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
                report, research_result = await asyncio.wait_for(
                    orchestrator.research_from_plan(
                        sub_questions,
                        provider=provider,
                        tools=tools,
                        emit=_EventSink(query_id),
                        should_cancel=lambda: query_id in _cancel_requested,
                        max_iters=settings.max_iters,
                        max_concurrency=settings.max_concurrency,
                        per_researcher_timeout=settings.per_researcher_timeout,
                    ),
                    timeout=settings.global_timeout,
                )
            await repository.complete_query(db, query_id, report, research_result)
        except TimeoutError:
            logger.warning("research job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Research timed out.")
        except OrchestratorCancelledError:
            logger.info("research job %s stopped by the user", query_id)
            await repository.fail_query(db, query_id, "Research was stopped.")
        except OrchestratorError as exc:
            logger.warning("research job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            logger.exception("research job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Research failed due to an internal error."
            )
        finally:
            _cancel_requested.discard(query_id)
