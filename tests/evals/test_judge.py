from app.agents.provider import LLMResponse, ToolCall
from app.agents.schemas import Claim, Report, ResearchPoint, ResearchResult, Source
from app.evals.judge import evaluate_full, judge


class _JudgeProvider:
    """Fake judge: dispatches on the dimension keyword in the system prompt, so it
    returns a deterministic score per dimension even under concurrent gather."""

    def __init__(self, scores: dict[str, int]) -> None:
        self.scores = scores  # keyword -> score

    async def __aenter__(self) -> "_JudgeProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def generate(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        system = messages[0].content or ""
        for keyword, score in self.scores.items():
            if keyword in system:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="j",
                            name="submit_judgment",
                            args={"score": score, "reasoning": f"{keyword} reason"},
                        )
                    ]
                )
        return LLMResponse(text="no dimension matched")


def _report() -> Report:
    return Report(
        content="A[1].",
        sources=[Source(title="S1", url="http://s1")],
        failed_subquestions=[],
    )


def _result() -> ResearchResult:
    return ResearchResult(
        points=[
            ResearchPoint(sub_question="q", claims=[Claim(text="a", source_ids=[1])])
        ],
        sources=[Source(title="S1", url="http://s1")],
        gaps=[],
    )


async def test_judge_scores_three_dimensions_with_result() -> None:
    provider = _JudgeProvider({"FAITHFULNESS": 5, "RELEVANCE": 4, "COVERAGE": 3})

    checks = await judge("the question", _report(), _result(), provider=provider)

    by_name = {c.name: c for c in checks}
    assert set(by_name) == {"faithfulness", "relevance", "coverage_quality"}
    assert by_name["faithfulness"].score == 1.0  # 5 -> (5-1)/4
    assert by_name["faithfulness"].passed is True
    assert by_name["relevance"].score == 0.75  # 4
    assert by_name["coverage_quality"].score == 0.5  # 3 -> below pass threshold
    assert by_name["coverage_quality"].passed is False


async def test_judge_skips_faithfulness_without_result() -> None:
    provider = _JudgeProvider({"RELEVANCE": 5, "COVERAGE": 5})

    checks = await judge("the question", _report(), provider=provider)

    assert {c.name for c in checks} == {"relevance", "coverage_quality"}


async def test_judge_degrades_to_neutral_on_malformed_output() -> None:
    class _Garbage:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def generate(self, messages, tools=None, tool_choice="auto"):
            return LLMResponse(text="I refuse to call the tool")

    checks = await judge("q", _report(), provider=_Garbage())

    assert all(c.score == 0.5 and c.passed is False for c in checks)
    assert all("no structured judgment" in c.detail for c in checks)


async def test_evaluate_full_merges_tier1_and_tier2() -> None:
    provider = _JudgeProvider({"FAITHFULNESS": 5, "RELEVANCE": 5, "COVERAGE": 5})

    result = await evaluate_full("q", _report(), _result(), provider=provider)

    names = {c.name for c in result.checks}
    assert names == {
        "report_citation_validity",
        "source_utilization",
        "point_grounding",
        "coverage",
        "faithfulness",
        "relevance",
        "coverage_quality",
    }
    assert result.passed is True
