from app.evals.summary import summarize
from app.evals.trace import MetricResult, RunScore


def test_a_metric_whose_judgments_all_failed_is_flagged_not_shown_as_empty() -> None:
    failed = MetricResult(
        name="response_relevancy",
        stage="response",
        reason="judge failed: HTTPStatusError: Client error '400 Bad Request'",
    )
    scores = [
        RunScore(golden_id=f"g{i}", category="fact", metrics=[failed])
        for i in range(3)
    ]

    summary = summarize(scores, [], meta={})

    row = next(line for line in summary.splitlines() if "response_relevancy" in line)
    assert "3 judge errors" in row
    assert "3 judgments failed" in summary  # called out above the tables
    assert "400 Bad Request" in summary  # with the first error, to act on


def test_measurements_still_show_their_mean() -> None:
    scores = [
        RunScore(
            golden_id="g",
            category="fact",
            metrics=[MetricResult(name="latency_seconds", stage="system", value=4.0)],
        )
    ]

    summary = summarize(scores, [], meta={})

    row = next(line for line in summary.splitlines() if "latency_seconds" in line)
    assert "mean 4.00" in row
    assert "judgments failed" not in summary
