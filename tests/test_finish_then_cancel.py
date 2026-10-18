import asyncio

import pytest

from app.db.session import finish_then_cancel


async def test_a_stop_waits_for_the_write_then_goes_through() -> None:
    """A run stopped mid-write used to cut the statement: the driver threw the
    connection away and the row (an event, a billing line) was lost."""
    started, written = asyncio.Event(), []

    async def write() -> None:
        started.set()
        await asyncio.sleep(0.05)
        written.append("row")

    task = asyncio.create_task(finish_then_cancel(write()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert written == ["row"]


async def test_without_a_stop_it_returns_the_result() -> None:
    async def write() -> int:
        return 7

    assert await finish_then_cancel(write()) == 7
