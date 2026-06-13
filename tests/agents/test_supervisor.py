from app.agents.provider import LLMResponse, ToolCall
from app.agents.supervisor import decide
from app.agents.tools import SearchHit


class _ScriptedProvider:
    """Returns scripted responses in order, recording the tool specs it was given
    so a test can assert which tools the supervisor exposed."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.tool_names: list[list[str]] = []

    async def __aenter__(self) -> "_ScriptedProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        self.tool_names.append([t.name for t in (tools or [])])
        return self.responses.pop(0)


class _FakeBackend:
    async def __aenter__(self) -> "_FakeBackend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [SearchHit(title="A page", url="http://a", content="snippet")]

    async def extract(self, url: str) -> str:
        return "full page text"


def _call(name: str, args: dict) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=name, name=name, args=args)])


async def _decide(provider, *, reports=None, message="a message", max_iters=4):
    return await decide(
        message,
        "context",
        provider=provider,
        backend=_FakeBackend(),
        reports=reports or [],
        max_iters=max_iters,
    )


async def test_decide_routes_to_research() -> None:
    provider = _ScriptedProvider(
        [_call("research", {"query": "what is X", "title": "About X"})]
    )
    decision = await _decide(provider, message="tell me about X")
    assert decision.action == "research"
    assert decision.query == "what is X"
    assert decision.title == "About X"  # the supervisor names the report


async def test_decide_routes_to_answer() -> None:
    provider = _ScriptedProvider([_call("answer", {"reply": "It is blue."})])
    decision = await _decide(provider)
    assert decision.action == "answer"
    assert decision.reply == "It is blue."


async def test_decide_routes_to_compose() -> None:
    provider = _ScriptedProvider(
        [_call("compose_report", {"instructions": "merge", "title": "Combined"})]
    )
    decision = await _decide(
        provider, reports=[("q1", "report one"), ("q2", "report two")]
    )
    assert decision.action == "compose"
    assert decision.instructions == "merge"
    assert decision.title == "Combined"


async def test_decide_reads_reports_then_composes() -> None:
    # A genuine tool loop: it reads the full reports first, then composes.
    provider = _ScriptedProvider(
        [
            _call("read_reports", {}),
            _call("compose_report", {"instructions": "combine them"}),
        ]
    )
    decision = await _decide(provider, reports=[("q1", "the full report text")])
    assert decision.action == "compose"
    assert decision.instructions == "combine them"
    # read_reports was offered as a tool on the first call
    assert "read_reports" in provider.tool_names[0]


async def test_decide_can_web_search_before_answering() -> None:
    provider = _ScriptedProvider(
        [
            _call("web_search", {"query": "today", "max_results": 3}),
            _call("answer", {"reply": "Found it."}),
        ]
    )
    decision = await _decide(provider)
    assert decision.action == "answer"
    assert decision.reply == "Found it."


async def test_decide_answer_without_reply_falls_back_to_research() -> None:
    # An "answer" with no actual reply is useless: nudge, then exhaust to research.
    provider = _ScriptedProvider(
        [
            _call("answer", {"reply": "   "}),
            _call("answer", {"reply": ""}),
        ]
    )
    decision = await _decide(provider, message="a message", max_iters=2)
    assert decision.action == "research"
    assert decision.query == "a message"  # the raw message is the safe fallback


async def test_decide_exhausts_to_research() -> None:
    # If it only ever calls a gather tool, the budget runs out and it researches.
    provider = _ScriptedProvider([_call("read_reports", {}), _call("read_reports", {})])
    decision = await _decide(provider, message="keep reading", max_iters=2)
    assert decision.action == "research"
    assert decision.query == "keep reading"
