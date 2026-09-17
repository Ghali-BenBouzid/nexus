"""The research jobs: plan, research, compose. Each runs off the request, on a
worker (JOB_QUEUE=redis) or in the API process (inline), see app.jobs."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import orchestrator, writer
from app.agents.consolidator import merge_results
from app.agents.narration import ThinkingProvider
from app.agents.orchestrator import OrchestratorCancelledError, OrchestratorError
from app.agents.planner import PlannerError, plan
from app.agents.provider import LLMProvider, ProviderCreditsError
from app.agents.schemas import AgentEvent, Report, ResearchResult
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import FetchPage, SearchBackend, WebSearch
from app.billing.metering import MeteredProvider
from app.core.config import settings
from app.db import session as db_session
from app.models.query import Query, QueryStatus
from app.research import repository
from app.research.dependencies import get_provider, get_search_backend

logger = logging.getLogger(__name__)


class EventSink:
    """The emit sink: persists each agent event so a polling client can tail the
    live feed (``GET /research/query/{id}/events``).

    Each event is written in its own short-lived session: the job's own session
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


HEARTBEAT_SECONDS = 5.0


@dataclass
class Liveness:
    """What a job learns while it runs: whether the user stopped its query."""

    stopped: bool = False


@asynccontextmanager
async def job_liveness(query_id: int) -> AsyncIterator[Liveness]:
    """Keep the query's heartbeat fresh while a job works on it, and watch for a
    stop. The job and the stop endpoint may run in different processes (a worker
    and the API), so the stop travels through the query's status: the endpoint
    marks it failed and the next beat sees it. Best-effort like the event feed:
    a failed write is logged, never fatal."""
    live = Liveness()
    done = asyncio.Event()

    async def beat() -> None:
        while not done.is_set():
            try:
                async with db_session.SessionLocal() as db:
                    status = await repository.touch_heartbeat(db, query_id)
                live.stopped = live.stopped or status == QueryStatus.failed
            except Exception:
                logger.exception("heartbeat write failed for query %s", query_id)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), HEARTBEAT_SECONDS)

    task = asyncio.create_task(beat())
    try:
        yield live
    finally:
        # Let the beat finish its write instead of cancelling it mid-query, which
        # makes SQLAlchemy throw the connection away.
        done.set()
        await task


def _metered(provider: LLMProvider | None, *, user_id: int, query_id: int):
    """The provider a job bills its calls through. An inline job reuses the
    request's (the tests' fakes); a worker builds its own from settings."""
    return MeteredProvider(
        provider or get_provider(), user_id=user_id, query_id=query_id
    )


async def _run_research_pipeline(
    query_id: int,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    make_coro: Callable[..., Awaitable[tuple[Report, ResearchResult]]],
) -> None:
    """Shared body for the two research-running jobs. Owns its own session, drives
    the given orchestrator coroutine under the global timeout, and always resolves
    the status. ``make_coro`` receives the live provider/tools/emit/should_cancel
    and returns the orchestrator coroutine to run (full ``run`` or the
    plan-confirmed ``research_from_plan``)."""
    async with db_session.SessionLocal() as db, job_liveness(query_id) as live:
        if not await repository.mark_running(db, query_id):
            return  # stopped while it waited in the queue
        try:
            backend = CachingSearchBackend(backend)
            async with provider, backend:
                tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
                report, research_result = await asyncio.wait_for(
                    make_coro(
                        provider=provider,
                        tools=tools,
                        emit=EventSink(query_id),
                        should_cancel=lambda: live.stopped,
                        # Tag the trace's root run with the query id so a run in
                        # LangSmith maps back to its row (stripped + ignored when
                        # tracing is off). Flows through make_coro into the
                        # @traced_step on orchestrator.run / research_from_plan.
                        langsmith_extra={"metadata": {"query_id": query_id}},
                    ),
                    timeout=settings.global_timeout,
                )
            # Only a running query completes, so a stop that landed during the
            # uncancellable consolidate/write tail keeps the run stopped.
            await repository.complete_query(db, query_id, report, research_result)
        except TimeoutError:
            # global_timeout fired (asyncio.wait_for raises TimeoutError)
            logger.warning("research job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Research timed out.")
        except OrchestratorCancelledError:
            # The stop endpoint already resolved the query as stopped.
            logger.info("research job %s stopped by the user", query_id)
        except (PlannerError, OrchestratorError, ProviderCreditsError) as exc:
            # our own domain errors carry safe, user-meaningful messages
            logger.warning("research job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            # unknown/SDK errors may embed secrets: log full server-side, store generic
            logger.exception("research job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Research failed due to an internal error."
            )


async def run_research_job(
    query_id: int,
    prompt: str,
    *,
    user_id: int,
    provider: LLMProvider | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """One-shot job: plan, research, consolidate, write."""
    await _run_research_pipeline(
        query_id,
        provider=_metered(provider, user_id=user_id, query_id=query_id),
        backend=backend or get_search_backend(),
        make_coro=lambda **kw: orchestrator.run(
            prompt,
            cap=settings.cap,
            max_iters=settings.max_iters,
            max_concurrency=settings.max_concurrency,
            per_researcher_timeout=settings.per_researcher_timeout,
            research_budget=settings.research_budget,
            writer_timeout=settings.writer_timeout,
            retry_cap=settings.planner_retry_cap,
            **kw,
        ),
    )


async def run_plan_job(
    query_id: int,
    prompt: str,
    *,
    user_id: int,
    feedback: str | None = None,
    provider: LLMProvider | None = None,
) -> None:
    """Phase 1 of a human-in-the-loop run: plan only, then pause for the user to
    confirm or revise (``status=awaiting_plan``). ``feedback`` re-plans after a
    rejection. A planner failure resolves the status to failed."""
    provider = _metered(provider, user_id=user_id, query_id=query_id)
    async with db_session.SessionLocal() as db, job_liveness(query_id):
        if not await repository.mark_running(db, query_id):
            return  # stopped while it waited in the queue
        try:
            emit = EventSink(query_id)
            async with provider:
                sub_questions = await asyncio.wait_for(
                    plan(
                        prompt,
                        provider=ThinkingProvider(provider, emit, agent="planner"),
                        emit=emit,
                        cap=settings.cap,
                        retry_cap=settings.planner_retry_cap,
                        feedback=feedback,
                    ),
                    timeout=settings.global_timeout,
                )
            # Only a running query takes the plan, so a stop that landed during
            # planning wins and the plan never re-surfaces for confirmation.
            await repository.set_plan(db, query_id, sub_questions)
        except TimeoutError:
            logger.warning("plan job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Planning timed out.")
        except (PlannerError, ProviderCreditsError) as exc:
            logger.warning("plan job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            logger.exception("plan job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Planning failed due to an internal error."
            )


async def run_compose_job(
    query_id: int,
    instructions: str,
    *,
    source_query_ids: list[int],
    user_id: int,
    provider: LLMProvider | None = None,
) -> None:
    """Compose a new report by merging the structured results of the conversation's
    existing reports and re-rendering them (guided by ``instructions``) into one
    longer report. No web search: it reuses the sources already gathered, so
    citations stay code-owned. Resolves the status to complete or failed."""
    provider = _metered(provider, user_id=user_id, query_id=query_id)
    async with db_session.SessionLocal() as db, job_liveness(query_id):
        if not await repository.mark_running(db, query_id):
            return  # stopped while it waited in the queue
        try:
            results = await _load_results(db, source_query_ids)
            if not results:
                await repository.fail_query(
                    db, query_id, "There were no reports to compose."
                )
                return
            merged = merge_results(results)
            emit = EventSink(query_id)
            async with provider:
                report = await asyncio.wait_for(
                    writer.write(
                        merged,
                        provider=ThinkingProvider(provider, emit, agent="writer"),
                        emit=emit,
                        guidance=instructions,
                        timeout=settings.writer_timeout,
                    ),
                    timeout=settings.global_timeout,
                )
            # Only a running query completes: a stop during the write wins.
            await repository.complete_query(db, query_id, report, merged)
        except TimeoutError:
            logger.warning("compose job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Composing the report timed out.")
        except ProviderCreditsError as exc:
            logger.warning("compose job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except Exception:
            logger.exception("compose job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Composing the report failed due to an internal error."
            )


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
    user_id: int,
    provider: LLMProvider | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """Phase 2: execute a confirmed plan (research -> consolidate -> write)."""
    await _run_research_pipeline(
        query_id,
        provider=_metered(provider, user_id=user_id, query_id=query_id),
        backend=backend or get_search_backend(),
        make_coro=lambda **kw: orchestrator.research_from_plan(
            sub_questions,
            max_iters=settings.max_iters,
            max_concurrency=settings.max_concurrency,
            per_researcher_timeout=settings.per_researcher_timeout,
            research_budget=settings.research_budget,
            writer_timeout=settings.writer_timeout,
            **kw,
        ),
    )
