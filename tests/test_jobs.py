from fastapi import BackgroundTasks

from app import jobs
from app.core.config import settings
from app.worker import JOBS, WorkerSettings


async def _job(query_id: int, *, provider: object = None) -> None:
    return None


class _FakePool:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict]] = []

    async def enqueue_job(self, name: str, **kwargs: object) -> None:
        self.enqueued.append((name, kwargs))


async def test_on_redis_only_plain_arguments_are_queued(monkeypatch) -> None:
    # The worker builds its own provider and backend: clients never cross Redis.
    pool = _FakePool()
    monkeypatch.setattr(settings, "job_queue", "redis")
    monkeypatch.setattr(jobs, "_pool", pool)

    await jobs.submit(
        BackgroundTasks(), _job, provider=object(), backend=object(), query_id=7
    )

    assert pool.enqueued == [("_job", {"query_id": 7})]


async def test_inline_jobs_reuse_the_request_clients(monkeypatch) -> None:
    monkeypatch.setattr(settings, "job_queue", "inline")
    provider = object()
    tasks = BackgroundTasks()

    await jobs.submit(tasks, _job, provider=provider, query_id=7)

    [task] = tasks.tasks
    assert task.func is _job
    assert task.kwargs == {"query_id": 7, "provider": provider}


def test_the_worker_runs_every_job_the_api_queues() -> None:
    # A job queued under a name the worker lacks would sit in Redis forever.
    assert {f.name for f in WorkerSettings.functions} == {j.__name__ for j in JOBS}
    assert {"route_message", "run_research_job", "review_plan_job"} <= {
        f.name for f in WorkerSettings.functions
    }
