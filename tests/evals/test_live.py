from app.evals.live import run_suite
from app.evals.runner import run_cases

# Reuse the orchestrator test's fake provider (dispatches on the system prompt, so
# it survives the concurrent researcher fan-out) and its knob set.
from tests.agents.test_orchestrator import _KNOBS, RoleProvider


async def test_run_suite_builds_and_scores_successful_runs() -> None:
    provider = RoleProvider(sub_questions=["q1", "q2"])

    cases, failures = await run_suite(
        ["a research prompt"],
        provider=provider,
        tools=[],
        global_timeout=30.0,
        **_KNOBS,
    )

    assert failures == []
    assert len(cases) == 1
    assert cases[0].name == "a research prompt"
    # the case is scorable end to end through the harness
    aggregate = run_cases(cases)
    assert aggregate.scores[0].evaluation.checks


async def test_run_suite_records_failed_runs_without_aborting() -> None:
    # The only sub-question fails, so the whole run raises OrchestratorError.
    provider = RoleProvider(sub_questions=["q1"], fail={"q1"})

    cases, failures = await run_suite(
        ["doomed prompt"],
        provider=provider,
        tools=[],
        global_timeout=30.0,
        **_KNOBS,
    )

    assert cases == []
    assert len(failures) == 1
    assert failures[0][0] == "doomed prompt"
    assert "OrchestratorError" in failures[0][1]
