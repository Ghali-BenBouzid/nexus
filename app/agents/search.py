import httpx
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


class SelfHostedBackend:
    """SearchBackend over two services we run ourselves, in place of Tavily.

    Tavily sold three things in two calls: a search index, a query-relevant
    excerpt attached to every result, and a page reader that strips boilerplate.
    Nothing open source does all three, so this splits the job:

    * **SearXNG** is the index. It is a metasearch proxy: it forwards the query
      to Google, Bing, DuckDuckGo and friends and normalises what comes back.
    * **Crawl4AI** is the reader. Its ``/md`` endpoint fetches a page in a real
      browser and returns pruned markdown, so a JS-rendered page is not an empty
      shell.

    What is genuinely lost is Tavily's excerpt: SearXNG hands back the search
    engine's own blurb, a sentence or two, rather than the part of the page that
    answers the query. Researchers will therefore read more pages than they used
    to. That is affordable in a way it was not before, because reading is now
    our own CPU rather than metered API calls.

    Only this class knows either service exists; the tools depend on the
    SearchBackend protocol, exactly as they did with Tavily.
    """

    def __init__(
        self,
        *,
        searxng_url: str,
        crawl4ai_url: str,
        crawl4ai_token: str | None = None,
        retry: RetryPolicy | None = None,
        search_timeout: float = 20.0,
        read_timeout: float = 60.0,
    ) -> None:
        self.searxng_url = searxng_url.rstrip("/")
        self.crawl4ai_url = crawl4ai_url.rstrip("/")
        self.crawl4ai_token = crawl4ai_token
        self.retry = retry or RetryPolicy()
        # Two budgets, because the calls are nothing alike: a metasearch query
        # answers in about a second, while reading a page starts a browser and
        # waits for the page to settle.
        self.search_timeout = search_timeout
        self.read_timeout = read_timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SelfHostedBackend":
        self._client = httpx.AsyncClient(follow_redirects=True)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _ready_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SelfHostedBackend must be used within 'async with'")
        return self._client

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        client = self._ready_client

        async def _call() -> dict:
            response = await client.get(
                f"{self.searxng_url}/search",
                params={"q": query, "format": "json"},
                timeout=self.search_timeout,
            )
            # Raise on 4xx/5xx so retry_async can tell a 429 or a 502 (worth
            # another go) from a 403 (the instance has JSON output switched off,
            # which no amount of retrying will fix).
            response.raise_for_status()
            return response.json()

        try:
            payload = await retry_async(_call, policy=self.retry)
        except Exception as exc:
            raise SearchError("web search failed") from exc
        results = payload.get("results") or []
        # SearXNG answers 200 even when every engine behind it refused the
        # query (rate limited, CAPTCHA, timed out). Read as "no results", that
        # told researchers their subject had nothing written about it, and a
        # deep run spent minutes concluding so. An empty page with engines that
        # failed is a failed search.
        refused = payload.get("unresponsive_engines") or []
        if not results and refused:
            reasons = ", ".join(f"{name}: {why}" for name, why in refused)
            raise SearchError(f"web search failed, the engines refused ({reasons})")
        # SearXNG returns a page of results, not a count we can ask for, so the
        # cap is applied here.
        return [
            SearchHit(
                title=result.get("title") or "",
                url=result.get("url") or "",
                content=result.get("content") or "",
            )
            for result in results[:max_results]
        ]

    async def extract(self, url: str) -> str:
        client = self._ready_client
        headers = (
            {"Authorization": f"Bearer {self.crawl4ai_token}"}
            if self.crawl4ai_token
            else {}
        )

        async def _call() -> dict:
            response = await client.post(
                f"{self.crawl4ai_url}/md",
                # f="fit" runs Crawl4AI's pruning filter, which drops nav, ads
                # and footers and returns the page's own prose. "raw" would hand
                # the whole document back and spend the context window on chrome.
                json={"url": url, "f": "fit", "c": "0"},
                headers=headers,
                timeout=self.read_timeout,
            )
            response.raise_for_status()
            return response.json()

        try:
            payload = await retry_async(_call, policy=self.retry)
        except Exception as exc:
            raise SearchError("page fetch failed") from exc
        return payload.get("markdown") or ""
