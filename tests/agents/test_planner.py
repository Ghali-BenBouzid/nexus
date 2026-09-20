"""The planner, with a scripted model: it fixes its own plan when it can, and
only a plan that never arrived is a failure.
"""

import pytest

from app.agents.planner import PlannerError, plan
from tests.agents.fakes import ScriptedModel, call, says

SUBMIT = "SubmitPlanArgs"  # the schema's name, as the model sees the tool


def _plan(*questions: str):
    return call(SUBMIT, sub_questions=list(questions))


async def test_a_plan_under_the_cap_is_taken_as_it_is() -> None:
    model = ScriptedModel([_plan("q1", "q2")])

    assert await plan("p", model=model, cap=3, retry_cap=2) == ["q1", "q2"]


async def test_blank_sub_questions_are_dropped() -> None:
    model = ScriptedModel([_plan("q1", "  ", "")])

    assert await plan("p", model=model, cap=3, retry_cap=2) == ["q1"]


async def test_an_over_cap_plan_is_sent_back_to_be_consolidated() -> None:
    model = ScriptedModel([_plan("a", "b", "c", "d"), _plan("a+b", "c+d")])

    assert await plan("p", model=model, cap=2, retry_cap=2) == ["a+b", "c+d"]
    # the second attempt was told why the first was refused
    told = model.seen[-1][-1].content
    assert "exceeds the limit of 2" in told


async def test_a_plan_still_over_the_cap_is_clamped_rather_than_lost() -> None:
    model = ScriptedModel([_plan("a", "b", "c"), _plan("a", "b", "c")])

    assert await plan("p", model=model, cap=2, retry_cap=1) == ["a", "b"]


async def test_an_empty_plan_is_retried_then_accepted() -> None:
    model = ScriptedModel([_plan(), _plan("q1")])

    assert await plan("p", model=model, cap=3, retry_cap=2) == ["q1"]


async def test_a_plan_that_never_arrives_is_a_failure() -> None:
    # Nothing usable after the retries: the run cannot continue on no plan.
    model = ScriptedModel([says("I would rather chat"), says("still chatting")])

    with pytest.raises(PlannerError):
        await plan("p", model=model, cap=3, retry_cap=1)
