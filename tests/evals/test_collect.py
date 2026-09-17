from app.agents.provider import LLMResponse, Message, ToolCall, Usage
from app.agents.tools import SearchHit
from app.evals.collect import collect_one
from app.evals.goldens import Golden

GOLDEN = Golden(
    id="g",
    category="explain",
    input="How does X work?",
    expected_behavior="explains X well",
)


class ScriptedProvider:
    """Routes to research, plans two sub-questions, searches once per researcher
    and cites what came back, then writes a report. Reports a cost on every call."""

    model = "fake-model"

    def __init__(self, route: str = "research") -> None:
        self.route = route

    async def __aenter__(self) -> "ScriptedProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(
        self, messages: list[Message], tools: object = None, tool_choice: str = "auto"
    ) -> LLMResponse:
        names = {tool.name for tool in tools or []}  # type: ignore[attr-defined]
        usage = Usage(input_tokens=10, output_tokens=5, cost_usd=0.001)
        if "answer" in names:
            args = (
                {"reply": "Hi there."}
                if self.route == "answer"
                else {"query": "How does X work in 2026?", "title": "X"}
            )
            return LLMResponse(
                tool_calls=[ToolCall(id="s", name=self.route, args=args)], usage=usage
            )
        if "submit_plan" in names:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="p",
                        name="submit_plan",
                        args={"sub_questions": ["what is X", "obscure q2"]},
                    )
                ],
                usage=usage,
            )
        if "submit_finding" in names:
            question = messages[1].content or ""
            searched = any(m.role == "tool" for m in messages)
            if not searched:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="w",
                            name="web_search",
                            args={"query": question, "max_results": 5},
                        )
                    ],
                    usage=usage,
                )
            found = "obscure" not in question
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="f",
                        name="submit_finding",
                        args={
                            "claims": (
                                [
                                    {
                                        "text": "X works like this.",
                                        "cited_source_ids": [0],
                                    }
                                ]
                                if found
                                else []
                            ),
                            "found_info": found,
                        },
                    )
                ],
                usage=usage,
            )
        return LLMResponse(text="X works like this [1].", usage=usage)


class Backend:
    """Returns a result for most queries and nothing for 'obscure' ones."""

    async def __aenter__(self) -> "Backend":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        if "obscure" in query:
            return []
        return [
            SearchHit(title="X explained", url="https://x.example", content="X is...")
        ]

    async def extract(self, url: str) -> str:
        return ""


async def test_research_run_is_recorded_stage_by_stage() -> None:
    trace = await collect_one(GOLDEN, provider=ScriptedProvider(), backend=Backend())

    assert trace.error is None
    assert trace.route == "research"
    assert trace.research_query == "How does X work in 2026?"
    assert trace.plan == ["what is X", "obscure q2"]

    found, empty = trace.researchers
    assert found.searches[0].query == "what is X"
    assert found.searches[0].hits[0].url == "https://x.example"
    assert found.succeeded
    assert found.evidence == ["X explained (https://x.example): X is..."]

    # the reported failure mode: the search came back empty, so nothing was found
    assert empty.searches[0].hits == []
    assert not empty.succeeded

    assert trace.gaps == ["obscure q2"]
    assert trace.consolidated == ["what is X: X works like this. [1]"]
    assert trace.report == "X works like this [1]."
    assert [s.url for s in trace.sources] == ["https://x.example"]
    assert set(trace.usage) == {"supervisor", "plan", "research", "write"}
    assert trace.usage["research"].calls == 4  # two rounds for each researcher
    assert round(trace.cost_usd, 4) == 0.007


async def test_direct_answer_stops_after_routing() -> None:
    trace = await collect_one(
        GOLDEN, provider=ScriptedProvider(route="answer"), backend=Backend()
    )

    assert trace.route == "answer"
    assert trace.reply == "Hi there."
    assert trace.plan == []
    assert trace.response == "Hi there."


class BrokenBackend(Backend):
    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        raise RuntimeError("search is down")


async def test_search_failures_are_recorded_not_raised() -> None:
    trace = await collect_one(
        GOLDEN, provider=ScriptedProvider(), backend=BrokenBackend()
    )

    errors = [s.error for r in trace.researchers for s in r.searches]
    assert errors and all("search is down" in e for e in errors)
    assert all(r.events for r in trace.researchers)  # the tool_error event is kept


async def test_a_plan_only_run_stops_before_any_search() -> None:
    trace = await collect_one(
        GOLDEN, provider=ScriptedProvider(), backend=Backend(), until="plan"
    )

    assert trace.error is None
    assert trace.until == "plan"
    assert trace.plan == ["what is X", "obscure q2"]
    assert trace.researchers == []
    assert trace.report is None
    assert set(trace.usage) == {"supervisor", "plan"}
