import pytest

from app.agents.rate_limit import AsyncTokenBucket


def test_take_paces_to_refill_rate():
    clock = [0.0]
    # 60/min => refill 1 token/sec; small burst capacity of 2
    bucket = AsyncTokenBucket(rate_per_min=60, capacity=2, time_fn=lambda: clock[0])

    assert bucket._take() == 0.0  # burst token 1 (2 -> 1)
    assert bucket._take() == 0.0  # burst token 2 (1 -> 0)

    wait = bucket._take()  # empty -> must wait ~1s for one token
    assert wait == pytest.approx(1.0, abs=0.01)

    clock[0] = 1.0  # one second passes -> one token refilled
    assert bucket._take() == 0.0


async def test_acquire_returns_immediately_when_tokens_available():
    bucket = AsyncTokenBucket(rate_per_min=6000)  # effectively unthrottled
    await bucket.acquire()  # should not hang
