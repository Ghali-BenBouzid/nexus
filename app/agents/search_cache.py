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

from app.agents.tools import SearchBackend, SearchHit


class CachingSearchBackend:
    def __init__(self, inner: SearchBackend) -> None:
        self.inner = inner
        self._search: dict[tuple[str, int], list[SearchHit]] = {}
        self._extract: dict[str, str] = {}

    async def __aenter__(self) -> "CachingSearchBackend":
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.inner.__aexit__(exc_type, exc, tb)

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        key = (query.strip().lower(), max_results)
        if key not in self._search:
            self._search[key] = await self.inner.search(query, max_results)
        return self._search[key]

    async def extract(self, url: str) -> str:
        if url not in self._extract:
            self._extract[url] = await self.inner.extract(url)
        return self._extract[url]
