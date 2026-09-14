"""Recorders that wrap the provider and search backend for an eval run.

Same decorator shape as CachingSearchBackend and MeteredProvider: the agents see
an ordinary provider and backend, and the trace gets everything they did.
"""

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.tools import MAX_PAGE_CHARS, SearchBackend, SearchHit, ToolSpec
from app.evals.trace import FetchCall, SearchCall, SearchHitRecord, StageUsage


def _describe(exc: Exception) -> str:
    """The error and its chained cause: the search and provider layers raise a
    generic message on purpose and keep the real reason in ``__cause__``."""
    text = f"{type(exc).__name__}: {exc}"
    cause = exc.__cause__
    return f"{text} ({type(cause).__name__}: {cause})" if cause else text


class RecordingSearchBackend:
    """Keeps every search and page fetch with what came back. The inner backend's
    lifecycle belongs to the collector, so entering this one does nothing."""

    def __init__(self, inner: SearchBackend) -> None:
        self.inner = inner
        self.searches: list[SearchCall] = []
        self.fetches: list[FetchCall] = []

    async def __aenter__(self) -> "RecordingSearchBackend":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        call = SearchCall(query=query)
        self.searches.append(call)
        try:
            hits = await self.inner.search(query, max_results)
        except Exception as exc:
            call.error = _describe(exc)
            raise
        call.hits = [
            SearchHitRecord(title=hit.title, url=hit.url, snippet=hit.content)
            for hit in hits
        ]
        return hits

    async def extract(self, url: str) -> str:
        call = FetchCall(url=url)
        self.fetches.append(call)
        try:
            text = await self.inner.extract(url)
        except Exception as exc:
            call.error = _describe(exc)
            raise
        call.text = text[:MAX_PAGE_CHARS]  # what the researcher was actually shown
        return text


class RecordingProvider:
    """Tallies model calls, tokens and cost per pipeline stage. The collector sets
    ``stage`` as the run moves on; concurrent researchers share the research stage.
    The inner provider is opened by the collector, so entering this does nothing."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.stage = "supervisor"
        self.usage: dict[str, StageUsage] = {}

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "unknown")

    async def __aenter__(self) -> "RecordingProvider":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        stage = self.stage
        response = await self.inner.generate(messages, tools, tool_choice)
        tally = self.usage.setdefault(stage, StageUsage())
        tally.calls += 1
        if response.usage is not None:
            tally.input_tokens += response.usage.input_tokens or 0
            tally.output_tokens += response.usage.output_tokens or 0
            tally.cost_usd += response.usage.cost_usd or 0.0
        return response
