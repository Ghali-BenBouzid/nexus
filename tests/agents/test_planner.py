import pytest

from app.agents.planner import PlannerError, plan
from app.agents.provider import FakeLLMProvider, LLMResponse, ToolCall


def _plan_response(*sub_questions: str) -> LLMResponse:
    return LLMResponse(
        tool_calls=[
            ToolCall(
                id="c",
                name="submit_plan",
                args={"sub_questions": list(sub_questions)},
            )
        ]
    )


async def test_plan_returns_sub_questions_under_cap() -> None:
    provider = FakeLLMProvider(responses=[_plan_response("q1", "q2", "q3")])

    result = await plan("big question", provider=provider, cap=5, retry_cap=2)

    assert result == ["q1", "q2", "q3"]
    # forced the specific tool
    assert provider.calls[-1][2] == "submit_plan"


async def test_plan_strips_blank_sub_questions() -> None:
    provider = FakeLLMProvider(responses=[_plan_response("q1", "  ", "q2")])
    result = await plan("q", provider=provider, cap=5, retry_cap=2)
    assert result == ["q1", "q2"]


async def test_plan_feedback_loop_consolidates_over_cap() -> None:
    provider = FakeLLMProvider(
        responses=[
            _plan_response("q1", "q2", "q3", "q4", "q5", "q6"),  # over cap
            _plan_response("q1", "q2", "q3"),  # consolidated
        ]
    )

    result = await plan("q", provider=provider, cap=5, retry_cap=2)

    assert result == ["q1", "q2", "q3"]
    assert len(provider.calls) == 2  # one retry


async def test_plan_clamps_when_still_over_after_retries() -> None:
    over = _plan_response("q1", "q2", "q3", "q4", "q5", "q6")
    provider = FakeLLMProvider(responses=[over, over])  # never consolidates

    result = await plan("q", provider=provider, cap=3, retry_cap=1)

    assert result == ["q1", "q2", "q3"]  # clamped to cap


async def test_plan_raises_on_empty_after_retries() -> None:
    # empty every time -> fed back, retried, then PlannerError once budget is spent
    provider = FakeLLMProvider(
        responses=[_plan_response(), _plan_response(), _plan_response()]
    )
    with pytest.raises(PlannerError):
        await plan("q", provider=provider, cap=5, retry_cap=2)


async def test_plan_recovers_from_empty_then_valid() -> None:
    # first call fumbles (empty); feedback lets the model recover on the retry
    provider = FakeLLMProvider(responses=[_plan_response(), _plan_response("q1", "q2")])

    result = await plan("q", provider=provider, cap=5, retry_cap=2)

    assert result == ["q1", "q2"]
    assert len(provider.calls) == 2
