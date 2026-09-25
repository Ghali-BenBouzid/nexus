"""Running one job: what every agent run shares before it does its own work.

A job is one run of the agents against one ``Query`` row: a chat turn, a deep
research run, a fact check, or the one-shot API run. What they share is
everything around the work. The query is claimed, a heartbeat says the job is
alive, the user's stop is watched for, every model call is billed to the
account, the search backend is cached and closed, failures become one clear
message on the row, and nothing is ever left in flight.

So that is what lives here: ``run_query`` wraps a piece of work in all of it and
hands it a ``Run``. What each job actually does lives next to the agents it
drives (app.conversations.service for a turn, app.research.deep for a deep run).
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.agents.model import Errors, Guard, Progress, StoppedError, retrying
from app.agents.planner import PlannerError
from app.agents.provider import ProviderCreditsError, ProviderError
from app.agents.report import as_stored, write_report
from app.agents.research import Limits, run_research
from app.agents.schemas import AgentEvent
from app.agents.search_cache import CachingSearchBackend
from app.agents.sources import Sources
from app.agents.tools import SearchBackend
from app.billing.metering import billing
from app.core.config import Effort, settings
from app.db import session as db_session
from app.models.query import QueryStatus
from app.research import bus, repository
from app.research.dependencies import chat_model, get_search_backend

logger = logging.getLogger(__name__)

PROVIDER_DOWN = "The model provider is not responding. Try again in a moment."


class RunCancelledError(Exception):
    """The user stopped the run."""


class RunFailedError(Exception):
    """The run failed for a reason worth showing the user as it is."""


# --- live feed and liveness -------------------------------------------------


# Events that exist only while someone is watching. A token is a fragment of a
# reply that is persisted whole when the turn ends: storing each would be
# hundreds of rows per turn to say what one row already says.
LIVE_ONLY = frozenset({"token"})


class EventSink:
    """The emit sink: every agent event, to whoever needs it.

    Two destinations, because they answer different questions. The durable feed
    (``query_events``) is what a browser reads when it arrives late or reloads,
    so it holds the run's stages. The bus is what a browser attached right now
    reads, so it carries everything, tokens included.

    Each durable event is written in its own short-lived session: the job's own
    session is single-threaded and not safe for the concurrent emits a researcher
    fan-out produces, and a fresh session per event sidesteps that entirely. A
    feed write must never sink the run, so any failure here is logged and
    swallowed."""

    def __init__(self, query_id: int) -> None:
        self.query_id = query_id

    async def __call__(self, event: AgentEvent) -> None:
        if event.type not in LIVE_ONLY:
            logger.info("agent[%s] %s", event.type, event.message)
            try:
                async with db_session.SessionLocal() as db:
                    await repository.add_event(db, self.query_id, event)
            except Exception:
                logger.exception(
                    "failed to persist agent event for query %s", self.query_id
                )
        await bus.publish(self.query_id, event)


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
            raise RunCancelledError("the run was stopped")
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


# --- one run ----------------------------------------------------------------


@dataclass
class Run:
    """Everything a job's work is handed: the models to call, the web to call
    them against, where progress goes, and what wraps every call.

    ``model`` thinks for the run (the supervisor, a deep lead), ``worker``
    researches and fact-checks, ``writer`` writes reports: see models_for."""

    query_id: int
    user_id: int
    model: BaseChatModel
    worker: BaseChatModel
    writer: BaseChatModel
    backend: SearchBackend
    emit: EventSink
    sources: Sources
    stopped: Callable[[], bool]
    _shared: list = field(default_factory=list)

    def middleware(self, agent: str, emit: Any = None, **data: Any) -> list:
        """What wraps every call one agent makes: the run-wide concerns, plus a
        progress tag naming the agent, so the feed can say who is working and
        nest a sub-agent's steps under the tool call that started it."""
        return [*self._shared, Progress(emit or self.emit, agent=agent, **data)]


def models_for(
    model: BaseChatModel | None, effort: Effort
) -> tuple[BaseChatModel, BaseChatModel, BaseChatModel]:
    """The run's model at ``effort``, its worker and its writer. An inline job
    reuses the request's model for all three (the tests' fake); a worker builds
    them from settings."""
    if model is not None:
        return model, model, model
    return (
        chat_model(effort=effort),
        chat_model(settings.worker_model, settings.worker_effort),
        chat_model(effort=settings.writer_effort),
    )


def _shared_middleware(*, stopped: Callable[[], bool]) -> list:
    """One clear error instead of an SDK traceback, no new call once the user has
    stopped, and retries where retrying can help.

    Billing and pacing are not here: middleware only sees an agent's calls, and
    the planner and the report writer call the model directly, so both ride on
    the model itself."""
    return [
        Errors(),
        Guard(should_cancel=stopped),
        retrying(settings.retry_max_attempts),
    ]


async def run_query(
    query_id: int,
    *,
    user_id: int,
    work: Callable[[Run], Awaitable[None]],
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
    timeout: float | None = None,
    effort: Effort = "high",
) -> None:
    """Claim the query, run ``work`` against it, and always resolve its status.

    ``work`` records the outcome itself (a reply, a report), because only it
    knows what the run produced. Everything that can go wrong on the way is
    resolved here, once, so no job has to remember to.
    """
    model, worker, writer = models_for(model, effort)
    backend = CachingSearchBackend(backend or get_search_backend())
    async with db_session.SessionLocal() as db, job_liveness(query_id) as live:
        if not await repository.mark_running(db, query_id):
            return  # stopped while it waited in the queue
        try:
            # Billing rides on the model, so a call is billed wherever it was
            # made, inside an agent or not.
            for each in (model, worker, writer):
                each.callbacks = [billing(user_id=user_id, query_id=query_id)]
            async with backend:
                run = Run(
                    query_id=query_id,
                    user_id=user_id,
                    model=model,
                    worker=worker,
                    writer=writer,
                    backend=backend,
                    emit=EventSink(query_id),
                    sources=Sources(),
                    stopped=lambda: live.stopped,
                    _shared=_shared_middleware(stopped=lambda: live.stopped),
                )
                await asyncio.wait_for(
                    live.unless_stopped(work(run)),
                    timeout=timeout or settings.global_timeout,
                )
        except TimeoutError:
            logger.warning("job timed out for query %s", query_id)
            await repository.fail_query(db, query_id, "The run timed out.")
        except (RunCancelledError, StoppedError):
            # The stop endpoint already resolved the query as stopped.
            logger.info("job %s stopped by the user", query_id)
        except (PlannerError, RunFailedError, ProviderCreditsError) as exc:
            # our own domain errors carry safe, user-meaningful messages
            logger.warning("job failed for query %s: %s", query_id, exc)
            await repository.fail_query(db, query_id, str(exc))
        except ProviderError:
            logger.warning("provider down for query %s", query_id, exc_info=True)
            await repository.fail_query(db, query_id, PROVIDER_DOWN)
        except Exception:
            # unknown/SDK errors may embed secrets: log full server-side, store generic
            logger.exception("job crashed for query %s", query_id)
            await repository.fail_query(
                db, query_id, "The run failed due to an internal error."
            )
        finally:
            # However it ended, tell anyone watching to stop watching. Without
            # this a browser holds its stream open until a proxy tires of it.
            await bus.publish(query_id, AgentEvent(type=bus.DONE, message=""))


# --- the one-shot API run ---------------------------------------------------


async def run_research_job(
    query_id: int,
    prompt: str,
    *,
    user_id: int,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
) -> None:
    """POST /research/query: research the prompt and write a report, with no
    conversation around it. The API-first path, and what the evals record."""

    async def work(run: Run) -> None:
        result = await run_research(
            prompt,
            model=run.model,
            worker=run.worker,
            backend=run.backend,
            sources=run.sources,
            emit=run.emit,
            middleware=run.middleware,
            limits=Limits.normal(),
        )
        report = await write_report(
            result,
            model=run.writer,
            emit=run.emit,
            timeout=settings.writer_timeout,
        )
        async with db_session.SessionLocal() as db:
            await repository.complete_query(
                db, query_id, report, as_stored(result, report)
            )

    await run_query(query_id, user_id=user_id, work=work, model=model, backend=backend)
