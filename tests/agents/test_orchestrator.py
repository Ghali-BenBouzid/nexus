import pytest

from app.agents.orchestrator import OrchestratorError, run
from app.agents.provider import LLMResponse, Message, ToolCall


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
                            "answer": f"answer to {sub_question}",
                            "cited_source_ids": [],
                            "found_info": True,
                        },
                    )
                ]
            )
        return LLMResponse(text="FINAL REPORT")


async def test_run_full_pipeline() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"])

    report, research_result = await run("big question", provider=provider, tools=[])

    assert report.content == "FINAL REPORT"
    assert report.failed_subquestions == []
    # the structured artifact carries one point per answered sub-question
    assert [p.sub_question for p in research_result.points] == ["q1", "q2"]
    assert research_result.gaps == []


async def test_run_degrades_on_partial_failure() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"], fail={"q2"})

    report, research_result = await run("big question", provider=provider, tools=[])

    # survivor produced a report; the failed sub-question is reported as a gap
    assert report.content == "FINAL REPORT"
    assert report.failed_subquestions == ["q2"]
    assert research_result.gaps == ["q2"]
    assert [p.sub_question for p in research_result.points] == ["q1"]


async def test_run_raises_when_all_researchers_fail() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"], fail={"q1", "q2"})

    with pytest.raises(OrchestratorError):
        await run("big question", provider=provider, tools=[])
