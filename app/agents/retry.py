import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 429 (rate limit) and 5xx (server hiccups) are worth retrying; 4xx like 400/401
# (bad request / bad key) are permanent and must fail fast.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class RetryPolicy(BaseModel):
    """Tuning for :func:`retry_async`. Production values come from Settings; the
    defaults here are a standalone fallback."""

    max_attempts: int = 3
    base_delay: float = 0.5  # seconds before the first retry
    max_delay: float = 8.0  # backoff ceiling


def _status_code(exc: Exception) -> int | None:
    """Best-effort HTTP status from an SDK/httpx exception, however it exposes it."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)  # httpx.HTTPStatusError
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def is_transient(exc: Exception) -> bool:
    """True for failures a retry could plausibly fix: a network-layer error, or a
    429/5xx response. Permanent errors (bad key, bad request, quota) return False
    so we fail fast instead of hammering a request that can't succeed."""
    if isinstance(exc, httpx.TimeoutException | httpx.TransportError):
        return True
    return _status_code(exc) in _TRANSIENT_STATUS


def _retry_after(exc: Exception) -> float | None:
    """The server's ``Retry-After`` hint (seconds), if present. On a 429 the API
    tells us exactly how long to wait, which beats guessing with backoff. We only
    parse the numeric (delta-seconds) form; an HTTP-date is ignored (fall back to
    computed backoff)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def retry_async[T](
    func: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    transient: Callable[[Exception], bool] = is_transient,
) -> T:
    """Await ``func()``, retrying transient failures with exponential backoff and
    jitter. Permanent errors raise immediately; the last transient error re-raises
    after ``policy.max_attempts``.

    Backoff sleeps run inside the caller's timeout budget (``asyncio.wait_for`` can
    cancel mid-sleep), so retries can never outrun the per-researcher / global
    timeouts that wrap the pipeline.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await func()
        except Exception as exc:
            if attempt >= policy.max_attempts or not transient(exc):
                raise
            # Prefer the server's Retry-After hint; otherwise exponential backoff,
            # capped, with jitter so researchers rate-limited together don't all
            # retry in lockstep. (A long Retry-After is fine: the per-researcher /
            # global wait_for can cancel the sleep, so retries never outrun them.)
            retry_after = _retry_after(exc)
            if retry_after is not None:
                delay = retry_after
            else:
                delay = min(policy.base_delay * 2 ** (attempt - 1), policy.max_delay)
                delay *= 0.5 + random.random() / 2  # 50-100% of the computed delay
            logger.warning(
                "transient %s (attempt %d/%d), retrying in %.2fs",
                type(exc).__name__,
                attempt,
                policy.max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
