import pytest

from app.agents.rate_limit import AsyncTokenBucket, RateLimiter


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


def test_take_with_cost_drains_multiple_tokens():
    clock = [0.0]
    # 6000/min => refill 100 tokens/sec; burst capacity 100
    bucket = AsyncTokenBucket(rate_per_min=6000, capacity=100, time_fn=lambda: clock[0])

    assert bucket._take(100) == 0.0  # drains the full burst at once
    wait = bucket._take(50)  # empty -> need 50 tokens at 100/sec -> 0.5s
    assert wait == pytest.approx(0.5, abs=0.01)


def test_take_clamps_cost_to_capacity():
    clock = [0.0]
    # 60/min => refill 1 token/sec; capacity 10
    bucket = AsyncTokenBucket(rate_per_min=60, capacity=10, time_fn=lambda: clock[0])

    # A cost larger than capacity must not deadlock: it is clamped to capacity.
    assert bucket._take(1000) == 0.0  # takes the whole bucket, doesn't hang
    wait = bucket._take(1000)  # empty -> refill a full capacity (10) at 1/sec
    assert wait == pytest.approx(10.0, abs=0.1)


async def test_acquire_returns_immediately_when_tokens_available():
    bucket = AsyncTokenBucket(rate_per_min=6000)  # effectively unthrottled
    await bucket.acquire()  # should not hang


async def test_rate_limiter_acquire_unthrottled_returns():
    rl = RateLimiter(rpm=10**9, tpm=10**9)
    await rl.acquire(5000)  # plenty of budget -> should not hang


def test_rate_limiter_request_bucket_paces_strictly():
    clock = [0.0]
    # 10 RPM with a strict burst of 1: requests space ~6s apart (1 per 6s), so a
    # run never fires a full minute's quota at once into a fixed-window API.
    rl = RateLimiter(rpm=10, tpm=10**9, time_fn=lambda: clock[0])
    assert rl._requests._take() == 0.0  # first request: the single burst token
    wait = rl._requests._take()  # empty -> wait ~6s (10/min)
    assert wait == pytest.approx(6.0, abs=0.05)


def test_rate_limiter_paces_on_tokens_not_just_requests():
    clock = [0.0]
    # Huge RPM but tiny TPM: the token bucket is the binding constraint.
    rl = RateLimiter(rpm=10**9, tpm=6000, time_fn=lambda: clock[0])
    # refill 100 tokens/sec, capacity 6000
    assert rl._tokens._take(6000) == 0.0  # drains the token budget
    wait = rl._tokens._take(100)  # empty -> 100 tokens at 100/sec -> 1s
    assert wait == pytest.approx(1.0, abs=0.01)
    assert rl._requests._take() == 0.0  # requests still wide open
