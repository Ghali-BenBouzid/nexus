import asyncio

from app.evals.goldens import Golden
from app.evals.scoring import collapse, judged_cases, score_run
from app.evals.trace import (
    ClaimRecord,
    MetricResult,
    ResearcherTrace,
    RunTrace,
    SearchCall,
    SearchHitRecord,
)

HIT = SearchHitRecord(title="t", url="https://a.example", snippet="s")


def _golden(**overrides: object) -> Golden:
    fields = {
        "id": "g",
        "category": "current",
        "input": "q",
        "expected_behavior": "x" * 30,
    }
    return Golden(**(fields | overrides))


def test_an_answer_is_judged_only_on_the_response() -> None:
    trace = RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        route="answer",
        reply="Hi.",
    )

    cases, direct = judged_cases(_golden(), trace)

    assert {c.name for c in cases} == {"expected_behavior", "response_relevancy"}
    assert direct == []


def test_a_research_run_is_judged_at_every_stage() -> None:
    trace = RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        route="research",
        research_query="q today",
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
        consolidated=["a: fact [1]"],
        gaps=["b"],
        report="fact [1]",
    )

    cases, direct = judged_cases(_golden(time_sensitive=True), trace)
    names = [c.name for c in cases]

    assert set(names) == {
        "expected_behavior",
        "response_relevancy",
        "temporal_awareness",
        "plan_relevance",
        "plan_searchability",
        "retrieval_relevance",
        "finding_relevance",
        "finding_faithfulness",
        "report_faithfulness",
        "report_completeness",
        "report_depth",
        "report_concision",
        "gap_honesty",
    }
    # the researcher that retrieved nothing is scored without a judge call
    assert [(m.name, m.score) for m in direct] == [("retrieval_relevance", 0.0)]
    # the judge sees today's date, so "current" can be checked
    temporal = next(c for c in cases if c.name == "temporal_awareness")
    assert "Today's date: 2026-09-14" in temporal.test_case.input


def test_per_researcher_results_collapse_into_one_score_per_run() -> None:
    merged = collapse(
        [
            MetricResult(
                name="retrieval_relevance", stage="research", score=1.0, passed=True
            ),
            MetricResult(
                name="retrieval_relevance", stage="research", score=0.0, passed=False
            ),
            MetricResult(name="plan_relevance", stage="plan", score=0.8, passed=True),
        ]
    )
    by_name = {m.name: m for m in merged}

    assert by_name["retrieval_relevance"].score == 0.5
    assert by_name["retrieval_relevance"].passed is False
    assert by_name["plan_relevance"].score == 0.8


async def test_without_a_judge_only_the_deterministic_checks_run() -> None:
    trace = RunTrace(
        golden_id="g",
        input="q",
        run_date="2026-09-14",
        model="m",
        route="answer",
        reply="Hi.",
    )

    score = await score_run(_golden(), trace, judge=None, limit=asyncio.Semaphore(1))

    names = {m.name for m in score.metrics}
    assert "run_completed" in names
    assert "expected_behavior" not in names
