from tavily import AsyncTavilyClient

from app.agents.retry import RetryPolicy, retry_async
from app.agents.tools import SearchHit


class SearchError(Exception):
    """A search-backend call failed (network/SDK error). Carries no SDK detail so
    a leaked API key can't ride along; the original is chained via ``__cause__``."""


class TavilyBackend:
    """SearchBackend implementation over the Tavily API. The only Tavily-aware
    code in the system; tools depend on the SearchBackend protocol, not on this.

    Use as an async context manager so the underlying HTTP client is opened and
    closed with the research job.
    """

    def __init__(self, api_key: str, retry: RetryPolicy | None = None) -> None:
        self.api_key = api_key
        self.retry = retry or RetryPolicy()
        self._client: AsyncTavilyClient | None = None

    async def __aenter__(self) -> "TavilyBackend":
        self._client = AsyncTavilyClient(api_key=self.api_key)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    @property
    def _ready_client(self) -> AsyncTavilyClient:
        if self._client is None:
            raise RuntimeError("TavilyBackend must be used within 'async with'")
        return self._client

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        client = self._ready_client

        async def _call() -> dict:
            return await client.search(query, max_results=max_results)

        try:
            response = await retry_async(_call, policy=self.retry)
        except Exception as exc:
            raise SearchError("web search failed") from exc
        return [
            SearchHit(
                title=result.get("title", ""),
                url=result.get("url", ""),
                content=result.get("content", ""),
            )
            for result in response.get("results", [])
        ]

    async def extract(self, url: str) -> str:
        client = self._ready_client

        async def _call() -> dict:
            # format="text" drops Tavily's markdown chrome (image refs, nav).
            return await client.extract(url, format="text")

        try:
            response = await retry_async(_call, policy=self.retry)
        except Exception as exc:
            raise SearchError("page fetch failed") from exc
        results = response.get("results", [])
        if not results:
            return ""
        return results[0].get("raw_content", "")
