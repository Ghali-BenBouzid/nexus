from app.evals.checks import deterministic_checks
from app.evals.goldens import Golden
from app.evals.trace import (
    ClaimRecord,
    ResearcherTrace,
    RunTrace,
    SearchCall,
    SearchHitRecord,
    SourceRecord,
)

HIT = SearchHitRecord(title="t", url="https://a.example", snippet="s")


def _golden(**overrides: object) -> Golden:
    fields = {
        "id": "g",
        "category": "explain",
        "input": "q",
        "expected_behavior": "x" * 30,
    }
    return Golden(**(fields | overrides))


def _by_name(golden: Golden, trace: RunTrace) -> dict:
    return {m.name: m for m in deterministic_checks(golden, trace)}


def _research_trace() -> RunTrace:
    return RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        tools=["research"],
        plan=["a", "b"],
        researchers=[
            ResearcherTrace(
                sub_question="a",
                searches=[SearchCall(query="a", hits=[HIT])],
                claims=[ClaimRecord(text="fact", source_urls=["https://a.example"])],
                found_info=True,
            ),
            ResearcherTrace(sub_question="b", searches=[SearchCall(query="b")]),
        ],
        reply="The answer, in English, is this fact [1]. More detail follows here.",
        sources=[SourceRecord(title="t", url="https://a.example")],
    )


def test_research_checks_explain_why_a_researcher_failed() -> None:
    checks = _by_name(_golden(), _research_trace())

    assert checks["route_correct"].passed
    assert checks["researcher_success"].score == 0.5
    assert "every search came back empty" in checks["researcher_success"].reason
    assert checks["search_yield"].score == 0.5
    assert "'b'" in checks["search_yield"].reason
    assert checks["report_citation_validity"].passed
    assert checks["source_utilization"].passed
    assert checks["language_match"].passed
    assert checks["run_completed"].passed


def test_a_rejected_submission_is_named_as_the_reason_not_nothing_found() -> None:
    # The researcher searched and got results, but its submit_finding call was
    # malformed on every try, so it ended with found_info=False and no claims.
    trace = _research_trace()
    trace.researchers[1] = ResearcherTrace(
        sub_question="b",
        searches=[SearchCall(query="b", hits=[HIT])],
        events=[
            "submit_invalid: submit_finding was malformed: ...",
            "researcher_forced: Max iterations reached",
        ],
    )

    reason = _by_name(_golden(), trace)["researcher_success"].reason

    assert "rejected as malformed" in reason
    assert "found nothing" not in reason


def test_researching_a_message_that_needed_a_direct_answer_is_a_routing_miss() -> None:
    checks = _by_name(_golden(expected_route="answer"), _research_trace())

    assert not checks["route_correct"].passed
    assert checks["route_correct"].reason.startswith("expected answer, got research")


def test_any_route_is_not_scored_and_an_answer_has_no_research_checks() -> None:
    trace = RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        reply="Hello, what would you like me to research?",
    )
    checks = _by_name(_golden(expected_route="any"), trace)

    assert "route_correct" not in checks
    assert "researcher_success" not in checks
    assert "search_yield" not in checks
    assert checks["run_completed"].passed


def test_a_failed_run_is_marked_incomplete() -> None:
    trace = RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        error="all researchers failed",
    )

    assert not _by_name(_golden(), trace)["run_completed"].passed
