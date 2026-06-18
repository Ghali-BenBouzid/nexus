import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator, writer
from app.agents.consolidator import merge_results
from app.agents.orchestrator import OrchestratorCancelledError, OrchestratorError
from app.agents.planner import PlannerError, plan
from app.agents.provider import LLMProvider
from app.agents.schemas import AgentEvent, Report, ResearchResult
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import FetchPage, SearchBackend, WebSearch
from app.core.config import settings
from app.db import session as db_session
from app.models.query import Query, QueryStatus
from app.research import repository

logger = logging.getLogger(__name__)


async def over_daily_cap(db: AsyncSession, user_id: int) -> bool:
    """Whether this user has hit the per-account research cap in the last 24h. The
    window rolls (rather than resetting at midnight) so it can't be doubled up
    across the boundary. Cheap COUNT on indexed columns; safe to call per request."""
    since = datetime.now(UTC) - timedelta(hours=24)
    count = await repository.count_queries_since(db, user_id, since)
    return count >= settings.daily_query_cap


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


async def _run_research_pipeline(
    query_id: int,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    make_coro: Callable[..., Awaitable[tuple[Report, ResearchResult]]],
) -> None:
    """Shared body for the two research-running jobs. Owns its own session (the
    request's is closed once the 202 is sent), drives the given orchestrator
    coroutine under the global timeout, and always resolves the status to complete
    or failed. ``make_coro`` receives the live provider/tools/emit/should_cancel
    and returns the orchestrator coroutine to run (full ``run`` or the
    plan-confirmed ``research_from_plan``)."""
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.running)
        try:
            backend = CachingSearchBackend(backend)
            async with provider, backend:
                tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
                report, research_result = await asyncio.wait_for(
                    make_coro(
                        provider=provider,
                        tools=tools,
                        emit=_EventSink(query_id),
                        should_cancel=lambda: query_id in _cancel_requested,
                        # Tag the trace's root run with the query id so a run in
                        # LangSmith maps back to its row (stripped + ignored when
                        # tracing is off). Flows through make_coro into the
                        # @traced_step on orchestrator.run / research_from_plan.
                        langsmith_extra={"metadata": {"query_id": query_id}},
                    ),
                    timeout=settings.global_timeout,
                )
            # A stop that lands during the uncancellable consolidate/write tail (after
            # the orchestrator's last checkpoint) must still prevent the run from being
            # saved as a finished report. The in-process set is the authoritative
            # cancel signal, so re-check it right before the terminal write.
            if query_id in _cancel_requested:
                raise OrchestratorCancelledError("stopped after the work finished")
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


async def run_research_job(
    query_id: int,
    prompt: str,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
) -> None:
    """One-shot background job: plan, research, consolidate, write."""
    await _run_research_pipeline(
        query_id,
        provider=provider,
        backend=backend,
        make_coro=lambda **kw: orchestrator.run(
            prompt,
            cap=settings.cap,
            max_iters=settings.max_iters,
            max_concurrency=settings.max_concurrency,
            per_researcher_timeout=settings.per_researcher_timeout,
            retry_cap=settings.planner_retry_cap,
            **kw,
        ),
    )


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
            # A stop requested during planning wins over the proposed plan, so the
            # paused query never re-surfaces as awaiting confirmation.
            if query_id in _cancel_requested:
                await repository.fail_query(db, query_id, "Research was stopped.")
            else:
                await repository.set_plan(db, query_id, sub_questions)
        except PlannerError as exc:
            logger.warning("plan job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            logger.exception("plan job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Planning failed due to an internal error."
            )
        finally:
            # Like the research jobs: never leave a stale cancel request behind, or a
            # later confirmed run for this id would abort the moment it starts.
            _cancel_requested.discard(query_id)


async def run_compose_job(
    query_id: int,
    instructions: str,
    *,
    source_query_ids: list[int],
    provider: LLMProvider,
) -> None:
    """Compose a new report by merging the structured results of the conversation's
    existing reports and re-rendering them (guided by ``instructions``) into one
    longer report. No web search: it reuses the sources already gathered, so
    citations stay code-owned. Resolves the status to complete or failed."""
    async with db_session.SessionLocal() as db:
        await repository.set_status(db, query_id, QueryStatus.running)
        try:
            results = await _load_results(db, source_query_ids)
            if not results:
                await repository.fail_query(
                    db, query_id, "There were no reports to compose."
                )
                return
            merged = merge_results(results)
            emit = _EventSink(query_id)
            async with provider:
                report = await asyncio.wait_for(
                    writer.write(
                        merged, provider=provider, emit=emit, guidance=instructions
                    ),
                    timeout=settings.global_timeout,
                )
            # A stop during the (uncancellable) write tail must still prevent the
            # composed report from being saved as finished.
            if query_id in _cancel_requested:
                await repository.fail_query(db, query_id, "Research was stopped.")
                return
            await repository.complete_query(db, query_id, report, merged)
        except TimeoutError:
            logger.warning("compose job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Composing the report timed out.")
        except Exception:
            logger.exception("compose job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Composing the report failed due to an internal error."
            )
        finally:
            _cancel_requested.discard(query_id)


async def _load_results(db: AsyncSession, query_ids: list[int]) -> list[ResearchResult]:
    """Rehydrate the stored ResearchResult of each source query, skipping any with
    no result or a malformed blob."""
    results: list[ResearchResult] = []
    for query_id in query_ids:
        query = await db.get(Query, query_id)
        if query is None or not query.result:
            continue
        try:
            results.append(ResearchResult(**query.result))
        except ValidationError:
            logger.warning("skipping unreadable result blob for query %s", query_id)
    return results


async def run_research_from_plan_job(
    query_id: int,
    sub_questions: list[str],
    *,
    provider: LLMProvider,
    backend: SearchBackend,
) -> None:
    """Phase 2: execute a confirmed plan (research -> consolidate -> write)."""
    await _run_research_pipeline(
        query_id,
        provider=provider,
        backend=backend,
        make_coro=lambda **kw: orchestrator.research_from_plan(
            sub_questions,
            max_iters=settings.max_iters,
            max_concurrency=settings.max_concurrency,
            per_researcher_timeout=settings.per_researcher_timeout,
            **kw,
        ),
    )
