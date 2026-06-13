import pytest

from app.agents.orchestrator import OrchestratorError, run
from app.agents.provider import LLMResponse, Message, ToolCall
from app.agents.schemas import AgentEvent

# orchestration knobs the service would supply from settings
_KNOBS = {
    "cap": 5,
    "max_iters": 5,
    "max_concurrency": 3,
    "per_researcher_timeout": 120.0,
    "retry_cap": 2,
}


class RoleProvider:
    """A fake provider that dispatches on the system prompt, so it works under the
    orchestrator's concurrent fan-out (unlike a single scripted queue)."""

    def __init__(self, sub_questions: list[str], fail: set[str] | None = None) -> None:
        self.sub_questions = sub_questions
        self.fail = fail or set()

    async def __aenter__(self) -> "RoleProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(
        self,
        messages: list[Message],
        tools: object = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        system = messages[0].content or ""
        if "research planner" in system:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="p",
                        name="submit_plan",
                        args={"sub_questions": self.sub_questions},
                    )
                ]
            )
        if "research agent" in system:
            sub_question = messages[1].content or ""
            if sub_question in self.fail:
                raise RuntimeError(f"researcher boom: {sub_question}")
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="f",
                        name="submit_finding",
                        args={
                            "claims": [
                                {
                                    "text": f"answer to {sub_question}",
                                    "cited_source_ids": [],
                                }
                            ],
                            "found_info": True,
                        },
                    )
                ]
            )
        return LLMResponse(text="FINAL REPORT")


async def test_run_full_pipeline() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"])

    report, research_result = await run(
        "big question", provider=provider, tools=[], **_KNOBS
    )

    assert report.content == "FINAL REPORT"
    assert report.failed_subquestions == []
    # the structured artifact carries one point per answered sub-question
    assert [p.sub_question for p in research_result.points] == ["q1", "q2"]
    assert research_result.gaps == []


async def test_run_degrades_on_partial_failure() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"], fail={"q2"})

    report, research_result = await run(
        "big question", provider=provider, tools=[], **_KNOBS
    )

    # survivor produced a report; the failed sub-question is reported as a gap
    assert report.content == "FINAL REPORT"
    assert report.failed_subquestions == ["q2"]
    assert research_result.gaps == ["q2"]
    assert [p.sub_question for p in research_result.points] == ["q1"]


async def test_run_raises_when_all_researchers_fail() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"], fail={"q1", "q2"})

    with pytest.raises(OrchestratorError):
        await run("big question", provider=provider, tools=[], **_KNOBS)


async def test_run_emits_indexed_researcher_lifecycle() -> None:
    # The live feed needs per-researcher index/total to render "researcher k/N".
    # The orchestrator owns those events because only it knows the index and total.
    events: list[AgentEvent] = []

    async def collect(event: AgentEvent) -> None:
        events.append(event)

    provider = RoleProvider(sub_questions=["q1", "q2"], fail={"q2"})

    await run("big question", provider=provider, tools=[], emit=collect, **_KNOBS)

    starts = {
        (e.data["index"], e.data["total"], e.data["sub_question"])
        for e in events
        if e.type == "researcher_start"
    }
    assert starts == {(1, 2, "q1"), (2, 2, "q2")}

    done = [e for e in events if e.type == "researcher_done"]
    assert [e.data["sub_question"] for e in done] == ["q1"]
    assert done[0].data["index"] == 1 and done[0].data["total"] == 2

    failed = [e for e in events if e.type == "researcher_failed"]
    assert [e.data["sub_question"] for e in failed] == ["q2"]
    assert failed[0].data["index"] == 2 and failed[0].data["total"] == 2
