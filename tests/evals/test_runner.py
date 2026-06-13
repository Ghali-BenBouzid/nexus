from app.agents.schemas import Claim, Report, ResearchPoint, ResearchResult, Source
from app.evals.runner import Case, format_aggregate, run_cases


def _src(n: int) -> list[Source]:
    return [Source(title=f"S{i}", url=f"http://s{i}") for i in range(1, n + 1)]


def _clean_case(name: str) -> Case:
    return Case(
        name=name,
        report=Report(content="A[1] B[2].", sources=_src(2), failed_subquestions=[]),
        result=ResearchResult(
            points=[
                ResearchPoint(
                    sub_question="q1", claims=[Claim(text="a", source_ids=[1])]
                ),
                ResearchPoint(
                    sub_question="q2", claims=[Claim(text="b", source_ids=[2])]
                ),
            ],
            sources=_src(2),
            gaps=[],
        ),
    )


def _bad_citation_case(name: str) -> Case:
    # Writer cites [3] with only two sources: the headline defect.
    return Case(
        name=name,
        report=Report(content="A[1] B[3].", sources=_src(2), failed_subquestions=[]),
        result=ResearchResult(
            points=[
                ResearchPoint(
                    sub_question="q1", claims=[Claim(text="a", source_ids=[1])]
                )
            ],
            sources=_src(2),
            gaps=["q2"],
        ),
    )


def test_run_cases_rolls_up_pass_rate_and_per_check_means() -> None:
    aggregate = run_cases([_clean_case("good"), _bad_citation_case("buggy")])

    assert aggregate.pass_rate == 0.5
    means = aggregate.mean_by_check()
    # good=1.0, buggy=0.5 on citation validity -> mean 0.75
    assert means["report_citation_validity"] == 0.75
    # source_utilization: good uses both (1.0); buggy leaves [2] dangling (0.5)
    assert means["source_utilization"] == 0.75


def test_format_aggregate_surfaces_the_failing_case_and_offender() -> None:
    aggregate = run_cases([_clean_case("good"), _bad_citation_case("buggy")])
    text = format_aggregate(aggregate)

    assert "[PASS] good" in text
    assert "[FAIL] buggy" in text
    assert "[3] out of range (1..2)" in text
    assert "Pass rate: 50%" in text
