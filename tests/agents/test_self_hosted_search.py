"""The self-hosted search backend, against the two APIs it actually speaks.

The request and response shapes here are the real ones: SearXNG's
``/search?format=json`` returns a ``results`` list of title/url/content, and
Crawl4AI's ``/md`` returns ``{"markdown": ...}``. A fake transport stands in for
the services so the contract is pinned without running either.
"""

import json

import httpx
import pytest

from app.agents.retry import RetryPolicy
from app.agents.search import SearchError, SelfHostedBackend

SEARXNG = "http://searxng:8080"
CRAWL4AI = "http://crawl4ai:11235"


def _backend(handler) -> SelfHostedBackend:
    """A backend whose HTTP goes to ``handler`` instead of the network."""
    backend = SelfHostedBackend(
        searxng_url=SEARXNG,
        crawl4ai_url=CRAWL4AI,
        # One attempt: these tests are about the mapping, not the backoff, and
        # retrying a deliberate failure only makes them slow.
        retry=RetryPolicy(max_attempts=1),
    )
    backend._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return backend


async def test_a_searxng_page_becomes_search_hits() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Rayleigh scattering",
                        "url": "https://example.org/rayleigh",
                        "content": "Shorter wavelengths scatter more.",
                    }
                ]
            },
        )

    backend = _backend(handler)
    hits = await backend.search("why is the sky blue", max_results=5)

    assert [hit.title for hit in hits] == ["Rayleigh scattering"]
    assert hits[0].url == "https://example.org/rayleigh"
    assert hits[0].content == "Shorter wavelengths scatter more."
    assert "format=json" in seen["url"]
    assert "q=why+is+the+sky+blue" in seen["url"]


async def test_searxng_returns_a_page_so_the_cap_is_applied_here() -> None:
    """There is no max_results to ask SearXNG for: it answers with a page of
    results, and taking only what was asked for is this backend's job."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": f"r{n}", "url": f"https://e.org/{n}", "content": "x"}
                    for n in range(20)
                ]
            },
        )

    hits = await _backend(handler).search("anything", max_results=3)

    assert len(hits) == 3


async def test_a_result_missing_its_fields_does_not_break_the_search() -> None:
    """Engines disagree about what they return, and SearXNG passes that through.
    A result with no snippet is still a link worth having."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"url": "https://e.org/1", "title": None}]}
        )

    [hit] = await _backend(handler).search("anything", max_results=5)

    assert hit.url == "https://e.org/1"
    assert hit.title == ""
    assert hit.content == ""


async def test_a_page_is_read_as_pruned_markdown() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"markdown": "# Title\n\nThe prose.", "success": True}
        )

    text = await _backend(handler).extract("https://example.org/page")

    assert text == "# Title\n\nThe prose."
    assert seen["path"] == "/md"
    assert seen["body"]["url"] == "https://example.org/page"
    # "fit" is the pruning filter: nav, ads and footers out, the page's own
    # prose in. "raw" would spend the context window on chrome.
    assert seen["body"]["f"] == "fit"


async def test_a_token_is_sent_when_the_reader_wants_one() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"markdown": "text"})

    backend = _backend(handler)
    backend.crawl4ai_token = "s3cret"
    await backend.extract("https://example.org/page")

    assert seen["auth"] == "Bearer s3cret"


async def test_an_empty_page_reads_as_nothing_rather_than_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    assert await _backend(handler).extract("https://example.org/page") == ""


@pytest.mark.parametrize("status", [403, 500])
async def test_a_refused_search_is_a_search_error(status: int) -> None:
    """403 is a SearXNG instance with JSON output switched off; 500 is one
    having a bad day. Both reach the agent as the same tool failure, and the
    reason is chained rather than repeated, so no internal URL rides along."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="nope")

    with pytest.raises(SearchError) as caught:
        await _backend(handler).search("anything", max_results=5)

    assert str(caught.value) == "web search failed"
    assert isinstance(caught.value.__cause__, httpx.HTTPStatusError)


async def test_a_page_that_will_not_load_is_a_fetch_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    with pytest.raises(SearchError) as caught:
        await _backend(handler).extract("https://example.org/page")

    assert str(caught.value) == "page fetch failed"


async def test_the_backend_refuses_to_work_unopened() -> None:
    """The client is created by ``async with``; using one without it is a wiring
    mistake and should say so rather than fail somewhere further down."""
    backend = SelfHostedBackend(searxng_url=SEARXNG, crawl4ai_url=CRAWL4AI)

    with pytest.raises(RuntimeError, match="async with"):
        await backend.search("anything", max_results=5)


async def test_opening_and_closing_it_manages_one_client() -> None:
    async with SelfHostedBackend(
        searxng_url=SEARXNG, crawl4ai_url=CRAWL4AI
    ) as backend:
        assert backend._client is not None
    assert backend._client is None


async def test_the_pair_is_refused_without_a_reader_token() -> None:
    """Crawl4AI binds loopback inside its own container until it has a token,
    so it reports itself healthy while being unreachable. Saying so once at
    startup beats every page read failing to connect."""
    from fastapi import HTTPException

    from app.core.config import settings
    from app.research.dependencies import get_search_backend

    was = (settings.searxng_url, settings.crawl4ai_url, settings.crawl4ai_token)
    settings.searxng_url, settings.crawl4ai_url, settings.crawl4ai_token = (
        SEARXNG,
        CRAWL4AI,
        None,
    )
    try:
        with pytest.raises(HTTPException) as caught:
            get_search_backend()
        assert "CRAWL4AI_TOKEN" in caught.value.detail
    finally:
        settings.searxng_url, settings.crawl4ai_url, settings.crawl4ai_token = was
