"""The worker: runs the jobs the API queues on Redis.

    uv run arq app.worker.WorkerSettings

Same code and database as the API, which only enqueues (app.jobs). The worker
enqueues too: a turn can start a deep research run or a fact check, and those go
back on the queue rather than riding on the turn that asked for them.

A job that is running when its worker stops is not retried, because a research
run spends money and is not safe to repeat blindly. Its heartbeat goes stale
instead, and reap_stalled resolves it: a deep run is handed back to a worker,
which resumes it from its last checkpoint, and everything else is failed so the
user sees an error rather than a run that never ends.
"""

import logging
from typing import Any

from arq import cron, func
from arq.connections import RedisSettings
from arq.worker import Function

from app import jobs
from app.conversations.service import route_message
from app.core.config import settings
from app.db import session as db_session
from app.jobs import Job
from app.observability import configure_tracing
from app.research import repository
from app.research.deep import close_graph, open_graph, run_deep_research_job
from app.research.factcheck import run_fact_check_job
from app.research.service import run_research_job

logger = logging.getLogger(__name__)

JOBS: tuple[Job, ...] = (
    route_message,
    run_research_job,
    run_deep_research_job,
    run_fact_check_job,
)

# A job beats every 5 s, so this long without one means its worker died.
STALE_AFTER_SECONDS = 90


def _task(job: Job) -> Function:
    """arq calls a job with its context first; ours take only their own kwargs."""

    async def run(ctx: dict[str, Any], **kwargs: Any) -> None:
        await job(**kwargs)

    return func(run, name=job.__name__, max_tries=1)


async def reap_stalled(ctx: dict[str, Any]) -> None:
    """Resolve the runs whose worker stopped beating. Deep runs are checkpointed,
    so they go back on the queue and pick up where they stopped; the rest are
    failed, because restarting them would only re-bill work already paid for."""
    async with db_session.SessionLocal() as db:
        resumable = await repository.stalled_deep_runs(db, STALE_AFTER_SECONDS)
        reaped = await repository.reap_stalled_queries(db, STALE_AFTER_SECONDS)
    for query_id in resumable:
        logger.warning("resuming deep research %s after its worker stopped", query_id)
        await jobs.spawn(run_deep_research_job, query_id=query_id)
    if reaped:
        logger.warning("failed %d run(s) whose job stopped responding", reaped)


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    # arq logs through its own handler; reaching the root one too prints each line
    # twice.
    logging.getLogger("arq").propagate = False
    configure_tracing()
    await jobs.open_queue()  # so a turn can queue the runs it starts
    await open_graph()


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_graph()
    await jobs.close_queue()


class WorkerSettings:
    functions = [_task(job) for job in JOBS]
    cron_jobs = [cron(reap_stalled, second=0, run_at_startup=True)]  # every minute
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    # Above the longest run's own backstop, so arq never cuts one the budgets bound.
    job_timeout = settings.deep_timeout + 60
    max_tries = 1
    keep_result = 60
