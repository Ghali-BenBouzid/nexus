from app.agents.provider import FakeLLMProvider, LLMResponse
from app.agents.schemas import ResearchPoint, ResearchResult, Source
from app.agents.writer import write


async def test_write_renders_points_via_provider() -> None:
    result = ResearchResult(
        points=[ResearchPoint(sub_question="q", answer="ans", source_ids=[1])],
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


async def test_write_short_circuits_when_no_points() -> None:
    result = ResearchResult(points=[], sources=[], gaps=["nothing found"])
    provider = FakeLLMProvider(responses=[])  # must NOT be called

    report = await write(result, provider=provider)

    assert "No relevant information" in report.content
    assert report.failed_subquestions == ["nothing found"]
    assert provider.calls == []
