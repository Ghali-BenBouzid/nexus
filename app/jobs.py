"""Where jobs run: queued for the worker, or in the API process.

A job is one step of a turn that calls models: routing a message, planning,
researching, composing. With JOB_QUEUE=redis the API only enqueues it and the
worker (app.worker) runs it, so no model call happens inside an HTTP request and
redeploying the API never kills a run. With JOB_QUEUE=inline it runs in the API
process after the response: the tests, or a one-process setup without Redis.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import BackgroundTasks
from langchain_core.language_models import BaseChatModel

from app.agents.tools import SearchBackend
from app.core.config import settings

Job = Callable[..., Awaitable[None]]

_pool: ArqRedis | None = None
# Inline mode only: a strong reference to every spawned task, because asyncio
# keeps only a weak one and a task nobody holds can be collected mid-run.
_spawned: set[asyncio.Task] = set()


async def open_queue() -> None:
    """Connect to Redis once, at startup (JOB_QUEUE=redis only). Both the API
    and the worker open it: the API to queue a turn, the worker to queue the
    background runs a turn starts."""
    global _pool
    if settings.job_queue != "redis":
        return
    try:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    except Exception as exc:
        raise RuntimeError(
            f"Redis is not reachable at {settings.redis_url}. Start Redis, or set "
            "JOB_QUEUE=inline to run jobs in the API process."
        ) from exc


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def spawn(job: Job, **kwargs: Any) -> None:
    """Queue a job from inside another job, with no request behind it.

    This is how a run the supervisor starts (deep research, a fact check) gets
    off the turn that asked for it: the tool returns at once and the run carries
    on in the background. Inline, there is no request left to hang a background
    task on, so it becomes a task of its own.
    """
    if settings.job_queue == "inline":
        task = asyncio.create_task(job(**kwargs))
        _spawned.add(task)
        task.add_done_callback(_spawned.discard)
        return
    if _pool is None:
        raise RuntimeError("The job queue is not open (open_queue at startup).")
    await _pool.enqueue_job(job.__name__, **kwargs)


async def submit(
    background_tasks: BackgroundTasks,
    job: Job,
    *,
    model: BaseChatModel | None = None,
    backend: SearchBackend | None = None,
    **kwargs: Any,
) -> None:
    """Run ``job`` off the request, under its function name. Inline, it reuses
    the request's model and backend (the tests' fakes). On Redis only ``kwargs``
    travel, plain ids and text, and the worker builds its own."""
    if settings.job_queue == "inline":
        clients = {"model": model, "backend": backend}
        kwargs |= {name: value for name, value in clients.items() if value is not None}
        background_tasks.add_task(job, **kwargs)
        return
    if _pool is None:
        raise RuntimeError("The job queue is not open (open_queue at startup).")
    await _pool.enqueue_job(job.__name__, **kwargs)
