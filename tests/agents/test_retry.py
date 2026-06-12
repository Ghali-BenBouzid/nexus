import httpx
import pytest

from app.agents.retry import RetryPolicy, is_transient, retry_async


def _http_error(
    status: int, headers: dict[str, str] | None = None
) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://test/v1/chat/completions")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_is_transient_covers_429_and_5xx_not_400():
    assert is_transient(_http_error(429)) is True
    assert is_transient(_http_error(503)) is True
    assert is_transient(_http_error(400)) is False
    assert is_transient(_http_error(401)) is False


async def test_retry_honors_retry_after_header(monkeypatch):
    # Record the delays retry_async sleeps for, without actually sleeping.
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    monkeypatch.setattr("app.agents.retry.asyncio.sleep", fake_sleep)

    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429, {"retry-after": "2"})
        return "ok"

    result = await retry_async(
        flaky, policy=RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=8.0)
    )
    assert result == "ok"
    assert slept == [2.0]  # used the header value, not the 0.5 base backoff


async def test_retry_falls_back_to_backoff_without_header(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    monkeypatch.setattr("app.agents.retry.asyncio.sleep", fake_sleep)

    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(503)  # no retry-after header
        return "ok"

    await retry_async(
        flaky, policy=RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=8.0)
    )
    # backoff with 50-100% jitter on a 0.5s base => within (0.25, 0.5]
    assert len(slept) == 1
    assert 0.25 <= slept[0] <= 0.5


async def test_retry_reraises_permanent_400(monkeypatch):
    monkeypatch.setattr("app.agents.retry.asyncio.sleep", lambda d: None)

    async def boom() -> str:
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_async(boom, policy=RetryPolicy(max_attempts=3))
