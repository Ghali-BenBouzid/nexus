"""A caching decorator over a SearchBackend.

Researchers fan out and often reach for the same query or the same page (a
canonical source surfaces for several sub-questions). This wrapper memoizes both
``search`` and ``extract`` for the life of one run, so each distinct query or URL
hits the real backend at most once. That saves Tavily quota and tokens without
the researchers needing to coordinate.

It implements the same protocol (and async-context-manager lifecycle) as the
backend it wraps, so it drops in transparently: the job wraps its backend once
and builds the tools against the wrapper.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.agents.tools import SearchBackend, SearchHit

_K = TypeVar("_K")
_V = TypeVar("_V")


class CachingSearchBackend:
    def __init__(self, inner: SearchBackend) -> None:
        self.inner = inner
        # The cached values are the in-flight tasks, not just finished results, so
        # two researchers asking for the same key concurrently share one backend
        # call instead of each issuing its own (the fan-out is exactly when that
        # happens). A failed call is evicted so a later attempt can retry.
        self._search: dict[tuple[str, int], asyncio.Future[list[SearchHit]]] = {}
        self._extract: dict[str, asyncio.Future[str]] = {}

    async def __aenter__(self) -> "CachingSearchBackend":
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.inner.__aexit__(exc_type, exc, tb)

    @staticmethod
    async def _dedup(
        cache: dict[_K, "asyncio.Future[_V]"],
        key: _K,
        call: Callable[[], Awaitable[_V]],
    ) -> _V:
        future = cache.get(key)
        if future is None:
            future = asyncio.ensure_future(call())
            cache[key] = future
        try:
            return await future
        except Exception:
            cache.pop(key, None)  # don't cache a failure
            raise

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        key = (query.strip().lower(), max_results)
        return await self._dedup(
            self._search, key, lambda: self.inner.search(query, max_results)
        )

    async def extract(self, url: str) -> str:
        return await self._dedup(self._extract, url, lambda: self.inner.extract(url))
