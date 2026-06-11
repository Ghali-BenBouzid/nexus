from app.agents.provider import FakeLLMProvider, LLMResponse, ToolCall
from app.agents.researcher import research
from app.agents.schemas import AgentEvent
from app.agents.tools import SearchHit, WebSearch


class FakeSearchBackend:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return self.hits[:max_results]

    async def extract(self, url: str) -> str:
        return ""


def _web_search_tool() -> WebSearch:
    hits = [
        SearchHit(title="A", url="http://a", content="alpha"),
        SearchHit(title="B", url="http://b", content="beta"),
    ]
    return WebSearch(backend=FakeSearchBackend(hits))


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id="c", name=name, args=dict(args))


async def test_research_searches_then_submits() -> None:
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(tool_calls=[_call("web_search", query="q", max_results=5)]),
            LLMResponse(
                tool_calls=[
                    _call(
                        "submit_finding",
                        answer="the answer",
                        cited_source_ids=[0],
                        found_info=True,
                    )
                ]
            ),
        ]
    )

    finding = await research(
        "sub q", provider=provider, tools=[_web_search_tool()], max_iters=5
    )

    assert finding.answer == "the answer"
    assert finding.found_info is True
    assert [s.url for s in finding.consulted_sources] == ["http://a", "http://b"]
    assert [s.url for s in finding.cited_sources] == ["http://a"]


async def test_research_recovers_from_malformed_submit() -> None:
    # first submit_finding omits the required 'answer' -> fed back; model recovers
    malformed = LLMResponse(
        tool_calls=[ToolCall(id="b", name="submit_finding", args={"found_info": True})]
    )
    good = LLMResponse(
        tool_calls=[
            _call("submit_finding", answer="ok", cited_source_ids=[], found_info=True)
        ]
    )
    provider = FakeLLMProvider(responses=[malformed, good])

    finding = await research(
        "sub q", provider=provider, tools=[_web_search_tool()], max_iters=5
    )

    assert finding.answer == "ok"
    assert len(provider.calls) == 2  # one retry after the malformed submit


async def test_research_soft_no_answer() -> None:
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                tool_calls=[
                    _call(
                        "submit_finding",
                        answer="couldn't find anything",
                        cited_source_ids=[],
                        found_info=False,
                    )
                ]
            ),
        ]
    )

    finding = await research(
        "sub q", provider=provider, tools=[_web_search_tool()], max_iters=5
    )

    assert finding.found_info is False
    assert finding.cited_sources == []


async def test_research_forces_finding_on_cap() -> None:
    search = LLMResponse(tool_calls=[_call("web_search", query="q", max_results=5)])
    forced = LLMResponse(
        tool_calls=[
            _call(
                "submit_finding", answer="forced", cited_source_ids=[], found_info=False
            )
        ]
    )
    # never submits during the loop -> cap hit -> one forced submit_finding
    provider = FakeLLMProvider(responses=[search, search, forced])

    finding = await research(
        "sub q", provider=provider, tools=[_web_search_tool()], max_iters=2
    )

    assert finding.answer == "forced"
    assert finding.found_info is False
    # the final call forced the specific tool
    assert provider.calls[-1][2] == "submit_finding"


async def test_research_emits_events() -> None:
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    provider = FakeLLMProvider(
        responses=[
            LLMResponse(tool_calls=[_call("web_search", query="q", max_results=5)]),
            LLMResponse(
                tool_calls=[
                    _call(
                        "submit_finding",
                        answer="a",
                        cited_source_ids=[],
                        found_info=True,
                    )
                ]
            ),
        ]
    )

    await research(
        "sub q",
        provider=provider,
        tools=[_web_search_tool()],
        emit=collect,
        max_iters=5,
    )

    types = [e.type for e in events]
    assert "researcher_start" in types
    assert "tool_call" in types
