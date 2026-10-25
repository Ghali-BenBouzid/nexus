from typing import Any

from app import worker


async def test_a_new_worker_sweeps_once_the_old_heartbeats_are_stale(
    monkeypatch,
) -> None:
    # The cron sweeps only twice a day, so a run left by the worker this one
    # replaced is resolved by these sweeps, after its heartbeat has gone stale.
    sweeps: list[float] = []
    slept = 0.0

    async def sleep(seconds: float) -> None:
        nonlocal slept
        slept += seconds

    async def reap(ctx: dict[str, Any]) -> None:
        sweeps.append(slept)
        if len(sweeps) == 1:
            raise RuntimeError("database blip")  # must not cancel the next sweep

    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    monkeypatch.setattr(worker, "reap_stalled", reap)

    await worker._sweep_after_restart({})

    assert sweeps == list(worker.RESTART_SWEEPS_SECONDS)
    assert sweeps[0] > worker.STALE_AFTER_SECONDS
    assert sweeps[1] > worker.READING_STALE_AFTER_SECONDS
