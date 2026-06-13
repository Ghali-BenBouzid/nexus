import pytest

from app.agents import writer as writer_module
from app.agents.provider import FakeLLMProvider, LLMResponse, Message, ProviderError
from app.agents.schemas import Claim, ResearchPoint, ResearchResult, Source
from app.agents.writer import write


class _FlakyProvider:
    """Fails with ProviderError for the first ``fail_times`` calls, then succeeds."""

    def __init__(self, fail_times: int, text: str = "Final report [1]") -> None:
        self.fail_times = fail_times
        self.text = text
        self.calls = 0

    async def __aenter__(self) -> "_FlakyProvider":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def generate(self, messages: list[Message], tools=None, tool_choice="auto"):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("LLM request failed")
        return LLMResponse(text=self.text)


async def test_write_renders_points_via_provider() -> None:
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=["a gap"],
    )
    provider = FakeLLMProvider(responses=[LLMResponse(text="Final report [1]")])

    report = await write(result, provider=provider)

    assert report.content == "Final report [1]"
    assert [s.url for s in report.sources] == ["http://a"]
    assert report.failed_subquestions == ["a gap"]
    # the rendered ResearchResult was handed to the model
    rendered = provider.calls[0][0][1].content
    assert "q" in rendered and "[1]" in rendered


async def test_write_strips_unbacked_citation_markers() -> None:
    # The writer slips in [2] and [5] though only one source exists. Code owns
    # citations, so the guard removes the fabricated markers and keeps the valid.
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=[],
    )
    provider = FakeLLMProvider(
        responses=[LLMResponse(text="Real claim[1]. Fake claim[2]. Another[5].")]
    )

    report = await write(result, provider=provider)

    assert report.content == "Real claim[1]. Fake claim. Another."
    assert "[2]" not in report.content and "[5]" not in report.content
    assert [s.url for s in report.sources] == ["http://a"]


async def test_write_splits_comma_grouped_citations() -> None:
    # The model groups citations as [1, 2][3]; the renderer needs one number per
    # bracket, so they are split into [1][2][3].
    result = ResearchResult(
        points=[
            ResearchPoint(
                sub_question="q", claims=[Claim(text="a", source_ids=[1, 2, 3])]
            )
        ],
        sources=[
            Source(title="A", url="http://a"),
            Source(title="B", url="http://b"),
            Source(title="C", url="http://c"),
        ],
        gaps=[],
    )
    provider = FakeLLMProvider(responses=[LLMResponse(text="A fact[1, 2][3].")])

    report = await write(result, provider=provider)

    assert report.content == "A fact[1][2][3]."


async def test_write_prunes_uncited_sources_and_renumbers() -> None:
    # Three sources exist, but the prose only cites the 1st and 3rd. The report's
    # source list is pruned to those, renumbered in order of first appearance.
    result = ResearchResult(
        points=[
            ResearchPoint(
                sub_question="q", claims=[Claim(text="ans", source_ids=[1, 2, 3])]
            )
        ],
        sources=[
            Source(title="A", url="http://a"),
            Source(title="B", url="http://b"),
            Source(title="C", url="http://c"),
        ],
        gaps=[],
    )
    provider = FakeLLMProvider(
        responses=[LLMResponse(text="First fact[3]. Second fact[1].")]
    )

    report = await write(result, provider=provider)

    # [3] cited first -> becomes [1]; [1] cited second -> becomes [2].
    assert report.content == "First fact[1]. Second fact[2]."
    assert [s.url for s in report.sources] == ["http://c", "http://a"]


def _no_sleep_writer(monkeypatch) -> None:
    # Don't actually sleep through the writer's retry backoff in tests.
    async def fake_sleep(_d: float) -> None:
        return None

    monkeypatch.setattr("app.agents.retry.asyncio.sleep", fake_sleep)


async def test_write_retries_transient_writer_failures(monkeypatch) -> None:
    # The final write call is UX-critical: retry it rather than degrade. Here the
    # provider fails twice, then succeeds, and we still get the real prose report.
    _no_sleep_writer(monkeypatch)
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=[],
    )
    provider = _FlakyProvider(fail_times=2)

    report = await write(result, provider=provider)

    assert provider.calls == 3  # two failures retried, third succeeded
    assert report.content == "Final report [1]"
    assert [s.url for s in report.sources] == ["http://a"]


async def test_write_raises_after_exhausting_writer_retries(monkeypatch) -> None:
    # If the writer never recovers, surface the failure (don't emit a raw dump).
    _no_sleep_writer(monkeypatch)
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=[],
    )
    provider = _FlakyProvider(fail_times=99)

    with pytest.raises(ProviderError):
        await write(result, provider=provider)
    assert provider.calls == writer_module._WRITER_RETRY.max_attempts


async def test_write_keeps_sources_when_report_cites_nothing() -> None:
    # A grounded report that omits every [n] marker must not drop its sources to an
    # empty panel (that reads as broken); keep the full list instead.
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a"), Source(title="B", url="http://b")],
        gaps=[],
    )
    provider = FakeLLMProvider(
        responses=[LLMResponse(text="A solid report with no inline markers.")]
    )

    report = await write(result, provider=provider)

    assert report.content == "A solid report with no inline markers."
    assert [s.url for s in report.sources] == ["http://a", "http://b"]


async def test_write_leaves_bracketed_integers_in_code_untouched() -> None:
    # A literal bracketed integer inside a code span (`arr[10]`) is not a citation:
    # with only one source it must survive, not be stripped as an unbacked marker.
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=[],
    )
    provider = FakeLLMProvider(
        responses=[LLMResponse(text="Use `arr[10]` to index the list [1].")]
    )

    report = await write(result, provider=provider)

    assert report.content == "Use `arr[10]` to index the list [1]."
    assert [s.url for s in report.sources] == ["http://a"]


async def test_write_short_circuits_when_no_points() -> None:
    result = ResearchResult(points=[], sources=[], gaps=["nothing found"])
    provider = FakeLLMProvider(responses=[])  # must NOT be called

    report = await write(result, provider=provider)

    assert "No relevant information" in report.content
    assert report.failed_subquestions == ["nothing found"]
    assert provider.calls == []


async def test_write_includes_guidance_in_the_prompt() -> None:
    # The compose path passes shaping guidance; it must reach the model's prompt.
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="ans", source_ids=[1])])
        ],
        sources=[Source(title="A", url="http://a")],
        gaps=[],
    )
    provider = FakeLLMProvider(responses=[LLMResponse(text="Merged report [1]")])

    report = await write(result, provider=provider, guidance="merge both and go deeper")

    assert report.content == "Merged report [1]"
    rendered = provider.calls[0][0][1].content
    assert "merge both and go deeper" in rendered
