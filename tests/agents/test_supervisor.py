from app.agents.provider import LLMResponse, ToolCall
from app.agents.supervisor import decide


class _DecisionProvider:
    def __init__(self, args: dict) -> None:
        self.args = args

    async def __aenter__(self) -> "_DecisionProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        return LLMResponse(
            tool_calls=[ToolCall(id="d", name="submit_decision", args=self.args)]
        )


async def test_decide_routes_to_research() -> None:
    provider = _DecisionProvider({"action": "research", "query": "what is X"})
    decision = await decide("tell me about X", "context", provider=provider)
    assert decision.action == "research"
    assert decision.query == "what is X"


async def test_decide_routes_to_answer() -> None:
    provider = _DecisionProvider({"action": "answer", "reply": "It is blue."})
    decision = await decide("what colour?", "a report", provider=provider)
    assert decision.action == "answer"
    assert decision.reply == "It is blue."


async def test_decide_falls_back_to_research_without_a_tool_call() -> None:
    class _Empty:
        async def __aenter__(self) -> "_Empty":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def generate(self, *a, **k) -> LLMResponse:
            return LLMResponse(text="no tool call")

    decision = await decide("a message", "context", provider=_Empty())
    assert decision.action == "research"
    assert decision.query == "a message"  # the raw message is the safe fallback


async def test_decide_answer_without_reply_falls_back_to_research() -> None:
    # An "answer" with no actual reply is useless, so do the work instead.
    provider = _DecisionProvider({"action": "answer", "reply": "   "})
    decision = await decide("a message", "context", provider=provider)
    assert decision.action == "research"
