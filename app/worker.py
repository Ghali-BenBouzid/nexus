"""The worker: runs the jobs the API queues on Redis.

    uv run arq app.worker.WorkerSettings

Same code and database as the API, which only enqueues (app.jobs). A job that is
running when its worker stops is not retried, since a research run spends money
and is not safe to repeat. Its heartbeat goes stale instead, and reap_stalled
fails the query, so the user sees an error rather than a run that never ends.
"""

import logging
from typing import Any

from arq import cron, func
from arq.connections import RedisSettings
from arq.worker import Function

from app.conversations.service import route_message
from app.core.config import settings
from app.db import session as db_session
from app.jobs import Job
from app.observability import configure_tracing
from app.research import repository
from app.research.service import (
    run_compose_job,
    run_plan_job,
    run_research_from_plan_job,
    run_research_job,
)

logger = logging.getLogger(__name__)

JOBS: tuple[Job, ...] = (
    route_message,
    run_plan_job,
    run_research_job,
    run_research_from_plan_job,
    run_compose_job,
)

# A job beats every 5 s, so this long without one means its worker died.
STALE_AFTER_SECONDS = 90


def _task(job: Job) -> Function:
    """arq calls a job with its context first; ours take only their own kwargs."""

    async def run(ctx: dict[str, Any], **kwargs: Any) -> None:
        await job(**kwargs)

    return func(run, name=job.__name__, max_tries=1)


async def reap_stalled(ctx: dict[str, Any]) -> None:
    async with db_session.SessionLocal() as db:
        reaped = await repository.reap_stalled_queries(db, STALE_AFTER_SECONDS)
    if reaped:
        logger.warning("failed %d query(ies) whose job stopped responding", reaped)


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    # arq logs through its own handler; reaching the root one too prints each line
    # twice.
    logging.getLogger("arq").propagate = False
    configure_tracing()


class WorkerSettings:
    functions = [_task(job) for job in JOBS]
    cron_jobs = [cron(reap_stalled, second=0, run_at_startup=True)]  # every minute
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_max_jobs
    # Above the jobs' own backstop, so arq never cuts a run the budgets bound.
    job_timeout = settings.global_timeout + 60
    max_tries = 1
    keep_result = 60
