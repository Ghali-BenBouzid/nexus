from app.agents.schemas import Report, ResearchPoint, ResearchResult, Source
from app.evals.metrics import (
    coverage,
    evaluate,
    point_grounding,
    report_citation_validity,
    source_utilization,
)


def _sources(n: int) -> list[Source]:
    return [Source(title=f"S{i}", url=f"http://s{i}") for i in range(1, n + 1)]


# ---- report_citation_validity ----


def test_citation_validity_passes_when_every_marker_resolves() -> None:
    report = Report(
        content="Water is denser than ice[1]. The gap widens at depth[2].",
        sources=_sources(2),
        failed_subquestions=[],
    )
    check = report_citation_validity(report)
    assert check.passed is True
    assert check.score == 1.0


def test_citation_validity_catches_marker_with_no_backing_source() -> None:
    # The known bug: the writer cites [3] when only two sources exist.
    report = Report(
        content="A claim[1]. Another claim[3].",
        sources=_sources(2),
        failed_subquestions=[],
    )
    check = report_citation_validity(report)
    assert check.passed is False
    assert check.score == 0.5  # one of two markers resolves
    assert check.offenders == ["[3] out of range (1..2)"]


def test_citation_validity_passes_trivially_when_no_markers() -> None:
    report = Report(content="No citations here.", sources=[], failed_subquestions=[])
    check = report_citation_validity(report)
    assert check.passed is True
    assert "no citation markers" in check.detail


# ---- source_utilization ----


def test_source_utilization_flags_dangling_sources() -> None:
    report = Report(
        content="Only the first is used[1].",
        sources=_sources(3),
        failed_subquestions=[],
    )
    check = source_utilization(report)
    assert check.passed is False
    assert check.score == 1 / 3
    assert check.offenders == [
        "source [2] listed but never cited",
        "source [3] listed but never cited",
    ]


def test_source_utilization_passes_when_all_cited() -> None:
    report = Report(
        content="First[1] and second[2].",
        sources=_sources(2),
        failed_subquestions=[],
    )
    assert source_utilization(report).passed is True


# ---- point_grounding ----


def test_point_grounding_flags_out_of_range_source_id() -> None:
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q1", answer="a", source_ids=[1]),
            ResearchPoint(sub_question="q2", answer="b", source_ids=[2, 5]),
        ],
        sources=_sources(2),
        gaps=[],
    )
    check = point_grounding(result)
    assert check.passed is False
    assert check.score == 2 / 3  # two of three ids in range
    assert check.offenders == ["'q2' cites [5] (1..2)"]


def test_point_grounding_passes_when_all_ids_in_range() -> None:
    result = ResearchResult(
        points=[ResearchPoint(sub_question="q", answer="a", source_ids=[1, 2])],
        sources=_sources(2),
        gaps=[],
    )
    assert point_grounding(result).passed is True


# ---- coverage ----


def test_coverage_is_fraction_of_answered_subquestions() -> None:
    result = ResearchResult(
        points=[
            ResearchPoint(sub_question="q1", answer="a", source_ids=[1]),
            ResearchPoint(sub_question="q2", answer="b", source_ids=[1]),
            ResearchPoint(sub_question="q3", answer="c", source_ids=[1]),
        ],
        sources=_sources(1),
        gaps=["q4"],
    )
    check = coverage(result)
    assert check.score == 0.75
    assert check.passed is True
    assert "3/4" in check.detail


def test_coverage_fails_with_no_subquestions() -> None:
    result = ResearchResult(points=[], sources=[], gaps=[])
    check = coverage(result)
    assert check.score == 0.0
    assert check.passed is False


# ---- evaluate ----


def test_evaluate_report_only_runs_prose_checks() -> None:
    report = Report(content="A[1] B[2].", sources=_sources(2), failed_subquestions=[])
    result = evaluate(report)
    names = {c.name for c in result.checks}
    assert names == {"report_citation_validity", "source_utilization"}
    assert result.passed is True


def test_evaluate_with_result_adds_structured_checks() -> None:
    report = Report(content="A[1].", sources=_sources(1), failed_subquestions=[])
    research = ResearchResult(
        points=[ResearchPoint(sub_question="q", answer="a", source_ids=[1])],
        sources=_sources(1),
        gaps=[],
    )
    result = evaluate(report, research)
    names = {c.name for c in result.checks}
    assert names == {
        "report_citation_validity",
        "source_utilization",
        "point_grounding",
        "coverage",
    }
    assert result.passed is True
    assert result.score == 1.0
