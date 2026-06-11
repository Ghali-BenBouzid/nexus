import asyncio
import time
from collections.abc import Callable

from app.core.config import settings


class AsyncTokenBucket:
    """Process-wide async rate limiter. Callers ``await acquire()`` and are paced
    to ``rate_per_min`` requests per minute (with an optional small burst), never
    rejected. Shared across all jobs so concurrent researchers and multiple
    visitors together stay under a provider's free RPM."""

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

    def _take(self) -> float:
        """Try to take one token. Returns 0.0 if taken, else seconds to wait."""
        now = self._time()
        self._tokens = min(
            self.capacity, self._tokens + (now - self._updated) * self.refill_per_sec
        )
        self._updated = now
        if self._tokens >= 1:
            self._tokens -= 1
            return 0.0
        return (1 - self._tokens) / self.refill_per_sec

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                wait = self._take()
            if wait <= 0:
                return
            await asyncio.sleep(wait)


# Process-wide singleton, sized to the active provider's free tier.
llm_rate_limiter = AsyncTokenBucket(settings.llm_rate_limit_per_min)
