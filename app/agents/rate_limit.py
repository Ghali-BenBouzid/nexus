import asyncio
import time
from collections.abc import Callable

from app.core.config import settings


class AsyncTokenBucket:
    """Process-wide async token bucket. Callers ``await acquire(cost)`` and are
    paced to ``rate_per_min`` units per minute (with an optional burst), never
    rejected. A unit is a request for an RPM bucket or a token for a TPM bucket.
    Shared across all jobs so concurrent researchers and multiple visitors
    together stay under a provider's free-tier limit."""

    def __init__(
        self,
        rate_per_min: int,
        *,
        capacity: int | None = None,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.refill_per_sec = max(1, rate_per_min) / 60.0
        self.capacity = float(
            capacity if capacity is not None else max(1, rate_per_min)
        )
        self._tokens = self.capacity
        self._time = time_fn
        self._updated = time_fn()
        self._lock = asyncio.Lock()

    def _take(self, cost: float = 1.0) -> float:
        """Try to take ``cost`` units. Returns 0.0 if taken, else seconds to wait.

        ``cost`` is clamped to the bucket capacity so a single oversized request
        (e.g. a token estimate above the per-minute ceiling) drains a full bucket
        rather than waiting forever for a level it can never reach."""
        cost = min(max(cost, 1.0), self.capacity)
        now = self._time()
        self._tokens = min(
            self.capacity, self._tokens + (now - self._updated) * self.refill_per_sec
        )
        self._updated = now
        if self._tokens >= cost:
            self._tokens -= cost
            return 0.0
        return (cost - self._tokens) / self.refill_per_sec

    async def acquire(self, cost: float = 1.0) -> None:
        while True:
            async with self._lock:
                wait = self._take(cost)
            if wait <= 0:
                return
            await asyncio.sleep(wait)


class RateLimiter:
    """Paces LLM calls under both a requests-per-minute and a tokens-per-minute
    ceiling. On free tiers TPM is usually the binding limit, so a caller estimates
    a request's token cost and ``await acquire(tokens)``; the limiter blocks until
    both the request and token budgets allow the call."""

    def __init__(
        self,
        rpm: int,
        tpm: int,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        # Strict burst of 1 on the request bucket: a low-RPM provider (e.g. Gemini
        # at ~10 RPM) counts requests in a fixed window, so a full-rate burst plus
        # retries would overflow that window and 429. Spacing requests evenly stays
        # under the limit. The token bucket keeps its full burst (TPM is large).
        self._requests = AsyncTokenBucket(rpm, capacity=1, time_fn=time_fn)
        self._tokens = AsyncTokenBucket(tpm, time_fn=time_fn)

    async def acquire(self, tokens: int) -> None:
        await self._requests.acquire(1)
        await self._tokens.acquire(max(1, tokens))


# Process-wide fallback, sized conservatively; dependencies builds a per-model
# limiter from each provider's published RPM/TPM and passes it to the provider.
llm_rate_limiter = RateLimiter(rpm=settings.llm_rate_limit_per_min, tpm=6_000)
