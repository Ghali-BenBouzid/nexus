"""The eval harness, recording a real turn.

A turn is one agent with tools now, so what the harness has to prove is that it
can still see inside them: which tools the supervisor reached for, what each
researcher behind a ``research`` call searched and found, and what the run cost,
without changing what the turn does.
"""

from langchain_core.outputs import ChatGeneration, ChatResult

from app.agents.tools import SearchHit
from app.evals.collect import collect_one
from app.evals.goldens import Golden
from tests.agents.fakes import ScriptedModel, call, says

GOLDEN = Golden(
    id="g",
    category="explain",
    input="How does X work?",
    expected_behavior="explains X well",
)


class PipelineModel(ScriptedModel):
    """A supervisor that researches (two sub-questions, one search each, one of
    them fruitless) and then answers. Every call reports a cost."""

    answers_directly: bool = False
    researched: bool = False

    def __init__(self, answers_directly: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.answers_directly = answers_directly

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        names = {
            tool.get("function", {}).get("name") or tool.get("name", "")
            for tool in (kwargs.get("tools") or [])
        }
        if "SubmitPlanArgs" in names:
            reply = call("SubmitPlanArgs", sub_questions=["what is X", "obscure q2"])
        elif "SubmitFindingArgs" in names:
            question = str(messages[1].content or "")
            searched = any(getattr(m, "type", "") == "tool" for m in messages)
            if not searched:
                reply = call("web_search", query=question, max_results=5)
            else:
                found = "obscure" not in question
                reply = call(
                    "SubmitFindingArgs",
                    claims=(
                        [{"text": "X works like this.", "cited_source_ids": [1]}]
                        if found
                        else []
                    ),
                    found_info=found,
                )
        elif self.answers_directly:
            reply = says("Hi there.")
        elif not self.researched:
            self.researched = True
            reply = call("research", question="How does X work in 2026?")
        else:
            reply = says("X works like this.[1]")
        _priced(reply)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _priced(message):
    """Every call reports tokens and a cost, as a real provider does."""
    message.usage_metadata = {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    message.response_metadata = {
        "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
        "model_name": "fake-model",
    }
    return message


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


async def test_a_turn_that_researches_is_recorded_all_the_way_down() -> None:
    trace = await collect_one(GOLDEN, model=PipelineModel(), backend=Backend())

    assert trace.error is None
    assert trace.tools == ["research"]
    assert trace.researched
    assert trace.research_query == "How does X work in 2026?"
    assert trace.plan == ["what is X", "obscure q2"]

    found, empty = trace.researchers
    # each researcher's own searches, told apart by the stage they ran under
    assert found.searches[0].query == "what is X"
    assert found.searches[0].hits[0].url == "https://x.example"
    assert found.succeeded
    assert found.evidence == ["X explained (https://x.example): X is..."]

    # the reported failure mode: the search came back empty, so nothing was found
    assert empty.searches[0].hits == []
    assert not empty.succeeded

    assert trace.gaps == ["obscure q2"]
    assert trace.consolidated == ["what is X: X works like this. [1]"]
    assert trace.response == "X works like this.[1]"
    assert [s.url for s in trace.sources] == ["https://x.example"]
    assert set(trace.usage) == {"supervisor", "plan", "research-1", "research-2"}
    assert trace.usage["research-1"].calls == 2  # search, then submit
    assert round(trace.cost_usd, 4) == 0.007


async def test_a_turn_that_answers_directly_records_no_research() -> None:
    trace = await collect_one(
        GOLDEN, model=PipelineModel(answers_directly=True), backend=Backend()
    )

    assert trace.tools == []
    assert not trace.researched
    assert trace.plan == []
    assert trace.researchers == []
    assert trace.response == "Hi there."


class BrokenBackend(Backend):
    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        raise RuntimeError("search is down")


async def test_search_failures_are_recorded_not_raised() -> None:
    trace = await collect_one(GOLDEN, model=PipelineModel(), backend=BrokenBackend())

    errors = [s.error for r in trace.researchers for s in r.searches]
    assert errors and all("search is down" in e for e in errors)
    # the tool_error events are kept so a post-mortem can say why
    assert any("tool_error" in line for line in trace.lifecycle)


async def test_a_plan_only_run_stops_before_any_search() -> None:
    trace = await collect_one(
        GOLDEN, model=PipelineModel(), backend=Backend(), until="plan"
    )

    assert trace.error is None
    assert trace.until == "plan"
    assert trace.plan == ["what is X", "obscure q2"]
    assert trace.researchers == []
    assert trace.response == ""
    assert set(trace.usage) == {"supervisor", "plan"}
