from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import SearchHit


class _CountingBackend:
    """Records how many times the real search/extract are invoked."""

    def __init__(self) -> None:
        self.searches = 0
        self.extracts = 0

    async def __aenter__(self) -> "_CountingBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.searches += 1
        return [SearchHit(title=query, url=f"http://{query}", content="snippet")]

    async def extract(self, url: str) -> str:
        self.extracts += 1
        return f"full text of {url}"


async def test_search_is_cached_by_query_and_size() -> None:
    inner = _CountingBackend()
    cache = CachingSearchBackend(inner)

    a = await cache.search("Solar Power", 5)
    b = await cache.search("solar power", 5)  # same after normalization
    assert a == b
    assert inner.searches == 1

    await cache.search("solar power", 3)  # different size -> a real call
    assert inner.searches == 2


async def test_extract_is_cached_by_url() -> None:
    inner = _CountingBackend()
    cache = CachingSearchBackend(inner)

    first = await cache.extract("http://example.com")
    second = await cache.extract("http://example.com")
    assert first == second
    assert inner.extracts == 1

    await cache.extract("http://other.com")
    assert inner.extracts == 2


async def test_context_manager_delegates_to_inner() -> None:
    inner = _CountingBackend()
    async with CachingSearchBackend(inner) as cache:
        assert isinstance(cache, CachingSearchBackend)
