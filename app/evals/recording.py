"""Recorders for an eval run: what the agents searched, and what they spent.

The search backend is wrapped the way the caching one is, so the agents see an
ordinary backend. Model usage rides along as middleware, which is where every
model call already passes.
"""

import time
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from app.agents.model import _usage_of as usage_of
from app.agents.tools import MAX_PAGE_CHARS, SearchBackend, SearchHit
from app.evals.trace import FetchCall, SearchCall, SearchHitRecord
from app.evals.trace import StageUsage as StageUsage_


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
        started = time.monotonic()
        try:
            hits = await self.inner.search(query, max_results)
        except Exception as exc:
            call.error = _describe(exc)
            raise
        finally:
            call.seconds = round(time.monotonic() - started, 1)
        call.hits = [
            SearchHitRecord(title=hit.title, url=hit.url, snippet=hit.content)
            for hit in hits
        ]
        return hits

    async def extract(self, url: str) -> str:
        call = FetchCall(url=url)
        self.fetches.append(call)
        started = time.monotonic()
        try:
            text = await self.inner.extract(url)
        except Exception as exc:
            call.error = _describe(exc)
            raise
        finally:
            call.seconds = round(time.monotonic() - started, 1)
        call.text = text[:MAX_PAGE_CHARS]  # what the researcher was actually shown
        return text


class StageUsage(AsyncCallbackHandler):
    """Tallies model calls, tokens, cost and latency per pipeline stage.

    A callback, not middleware: the planner and the writer call the model
    directly, and a stage that spends nothing because nobody was watching is
    worse than no number at all. The collector moves ``stage`` as the run goes;
    concurrent researchers share the research stage.
    """

    def __init__(self) -> None:
        self.stage = "supervisor"
        self.usage: dict[str, StageUsage_] = {}
        self._started: dict[UUID, tuple[str, float]] = {}

    async def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._started[run_id] = (self.stage, time.monotonic())

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kw) -> None:
        self._started[run_id] = (self.stage, time.monotonic())

    async def on_llm_end(self, response: LLMResult, *, run_id, **kwargs) -> None:
        stage, started = self._started.pop(run_id, (self.stage, time.monotonic()))
        tally = self._tally(stage, time.monotonic() - started)
        for generation in response.generations:
            for item in generation:
                message = getattr(item, "message", None)
                counted = usage_of(message) if message is not None else None
                if counted:
                    tally.input_tokens += counted.get("input_tokens") or 0
                    tally.output_tokens += counted.get("output_tokens") or 0
                    tally.cost_usd += counted.get("cost_usd") or 0.0

    async def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        stage, started = self._started.pop(run_id, (self.stage, time.monotonic()))
        self._tally(stage, time.monotonic() - started)

    def _tally(self, stage: str, took: float) -> StageUsage_:
        tally = self.usage.setdefault(stage, StageUsage_())
        tally.calls += 1
        tally.seconds = round(tally.seconds + took, 1)
        tally.slowest_call_seconds = round(max(tally.slowest_call_seconds, took), 1)
        return tally
