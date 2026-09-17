"""The jobs that run the research graph (app.agents.orchestrator), on a worker
(JOB_QUEUE=redis) or in the API process (inline), see app.jobs.

A job runs the graph for one query and mirrors what happens onto the query row,
which is what the API serves: the supervisor's decision names the turn, a pause
for the plan sets awaiting_plan, the report completes it. The graph keeps its own
state in the checkpointer, and only while a run is paused on its plan."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import (
    SERDE,
    Deps,
    OrchestratorCancelledError,
    OrchestratorError,
    Review,
    compile_graph,
    run_config,
)
from app.agents.planner import PlannerError
from app.agents.provider import LLMProvider, ProviderCreditsError, ProviderError
from app.agents.schemas import AgentEvent
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import SearchBackend
from app.billing.metering import MeteredProvider
from app.core.config import settings
from app.db import session as db_session
from app.models.query import QueryStatus
from app.research import repository
from app.research.dependencies import get_provider, get_search_backend

logger = logging.getLogger(__name__)

PROVIDER_DOWN = "The model provider is not responding. Try again in a moment."
PLAN_EXPIRED = "This plan is no longer available. Send the question again."

# Called with the supervisor's decision, while the run goes on.
OnRoute = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


# --- the graph and its checkpointer -----------------------------------------

_graph: CompiledStateGraph | None = None
_pool: AsyncConnectionPool | None = None


def _conninfo() -> str:
    """The app's database URL, as psycopg (the checkpointer's driver) takes it."""
    url = make_url(settings.database_url).set(drivername="postgresql")
    if settings.database_ssl:
        url = url.update_query_dict({"sslmode": "require"})
    return url.render_as_string(hide_password=False)


async def open_graph(*, in_memory: bool = False) -> None:
    """Compile the graph over its checkpointer, once per process that runs jobs:
    the worker, or the API with JOB_QUEUE=inline. ``in_memory`` is for the tests,
    whose SQLite database the Postgres checkpointer cannot use."""
    global _graph, _pool
    if in_memory:
        _graph = compile_graph(InMemorySaver(serde=SERDE))
        return
    _pool = AsyncConnectionPool(
        _conninfo(),
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _pool.open()
    checkpointer = AsyncPostgresSaver(_pool, serde=SERDE)
    # Creates and migrates its own tables, outside Alembic. Idempotent.
    # ponytail: two workers booting at once can race here; the loser restarts.
    await checkpointer.setup()
    _graph = compile_graph(checkpointer)


async def close_graph() -> None:
    global _graph, _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    _graph = None


def _get_graph() -> CompiledStateGraph:
    if _graph is None:
        raise RuntimeError("The research graph is not open (open_graph at startup).")
    return _graph


# --- live feed and liveness ------------------------------------------------


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

    stop: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def stopped(self) -> bool:
        return self.stop.is_set()

    async def unless_stopped(self, work: Awaitable[Any]) -> Any:
        """Await ``work``, but cancel it as soon as the user stops the query,
        wherever it is, a model call included. Checking only between steps let a
        stopped run's writer finish its report, billed, and then drop it."""
        task = asyncio.ensure_future(work)
        stop = asyncio.ensure_future(self.stop.wait())
        try:
            await asyncio.wait({task, stop}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.cancel()
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if task.cancelled():
            raise OrchestratorCancelledError("research was stopped")
        return task.result()


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
                if status == QueryStatus.failed:
                    live.stop.set()
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


# --- running the graph ------------------------------------------------------


def _metered(provider: LLMProvider | None, *, user_id: int, query_id: int):
    """The provider a job bills its calls through. An inline job reuses the
    request's (the tests' fakes); a worker builds its own from settings."""
    return MeteredProvider(
        provider or get_provider(), user_id=user_id, query_id=query_id
    )


async def run_graph(
    query_id: int,
    graph_input: dict[str, Any] | Command,
    *,
    provider: LLMProvider,
    backend: SearchBackend,
    on_route: OnRoute | None = None,
) -> None:
    """Run the graph for one query (or resume it, given a Command) and always
    resolve the query's status. ``provider`` bills to the query's owner."""
    graph = _get_graph()
    config = run_config(query_id)
    async with db_session.SessionLocal() as db, job_liveness(query_id) as live:
        if not await repository.mark_running(db, query_id):
            return  # stopped while it waited in the queue
        if (
            isinstance(graph_input, Command)
            and not (await graph.aget_state(config)).next
        ):
            # Nothing is paused under this query: a plan from before the graph.
            await repository.fail_query(db, query_id, PLAN_EXPIRED)
            return
        paused = False
        try:
            backend = CachingSearchBackend(backend)
            async with provider, backend:
                deps = Deps(
                    provider=provider,
                    backend=backend,
                    emit=EventSink(query_id),
                    should_cancel=lambda: live.stopped,
                )
                updates = graph.astream(
                    graph_input,
                    config,
                    context=deps,
                    stream_mode="updates",
                    # Checkpoint only when the run stops (a pause, the end), not
                    # after every step: nothing resumes a run that crashed.
                    # ponytail: "async" would let a redeployed worker pick one up.
                    durability="exit",
                )
                paused = await asyncio.wait_for(
                    live.unless_stopped(_mirror(db, query_id, updates, on_route)),
                    timeout=settings.global_timeout,
                )
        except TimeoutError:
            logger.warning("research job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "Research timed out.")
        except OrchestratorCancelledError:
            # The stop endpoint already resolved the query as stopped.
            logger.info("research job %s stopped by the user", query_id)
        except (PlannerError, OrchestratorError, ProviderCreditsError) as exc:
            # our own domain errors carry safe, user-meaningful messages
            logger.warning("research job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except ProviderError:
            logger.warning("provider down for query %s", query_id, exc_info=True)
            await repository.fail_query(db, query_id, PROVIDER_DOWN)
        except Exception:
            # unknown/SDK errors may embed secrets: log full server-side, store generic
            logger.exception("research job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "Research failed due to an internal error."
            )
        finally:
            if not paused:
                await _forget(graph, query_id)


async def _mirror(
    db: AsyncSession,
    query_id: int,
    updates: AsyncIterator[dict[str, Any]],
    on_route: OnRoute | None,
) -> bool:
    """Mirror the run onto the query row as each node finishes. Returns whether
    the run paused for the user to review the plan."""
    state: dict[str, Any] = {}
    paused = False
    # Read the stream to its end, even past the pause: the graph saves the
    # paused checkpoint as the stream closes.
    async for chunk in updates:
        for node, update in chunk.items():
            if node == "__interrupt__":
                paused = True
                continue
            state |= update or {}
            if node == "supervisor":
                if update["route"] != "answer":
                    await repository.update_turn(
                        db, query_id, prompt=update["prompt"], title=update["title"]
                    )
                if on_route is not None:
                    await on_route(db, update)

    # Each write only moves a running query, so a stop that landed meanwhile wins.
    if paused:
        await repository.set_plan(db, query_id, state["plan"])
    elif state.get("route") == "answer":
        await repository.complete_answer(db, query_id, state["reply"])
    else:
        await repository.complete_query(db, query_id, state["report"], state["result"])
    return paused


async def _forget(graph: CompiledStateGraph, query_id: int) -> None:
    """Drop a finished run's checkpoint: there is nothing left to resume."""
    try:
        await graph.checkpointer.adelete_thread(str(query_id))
    except Exception:
        logger.exception("could not delete the checkpoint of query %s", query_id)


# --- the jobs ---------------------------------------------------------------


async def run_research_job(
    query_id: int,
    prompt: str,
    *,
    user_id: int,
    provider: LLMProvider | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """A one-shot run (POST /research/query): plan, research and write, with no
    pause for the plan."""
    await run_graph(
        query_id,
        {"prompt": prompt, "auto_approve": True},
        provider=_metered(provider, user_id=user_id, query_id=query_id),
        backend=backend or get_search_backend(),
    )


async def review_plan_job(
    query_id: int,
    *,
    user_id: int,
    approved: bool,
    feedback: str = "",
    provider: LLMProvider | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """Resume a run paused on its plan with the user's answer. A confirm
    researches and writes; a revise plans again with the feedback and pauses."""
    await run_graph(
        query_id,
        Command(resume=Review(approved=approved, feedback=feedback)),
        provider=_metered(provider, user_id=user_id, query_id=query_id),
        backend=backend or get_search_backend(),
    )
