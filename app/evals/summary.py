"""Turn a scored run into a readable summary: per stage, per category, and the
specific failures worth reading first."""

from statistics import mean

from app.evals.scoring import THRESHOLD
from app.evals.trace import MetricResult, RunScore, RunTrace

STAGES = ["routing", "plan", "research", "report", "response", "system"]
_WORST_SHOWN = 12


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _results(scores: list[RunScore], name: str) -> list[MetricResult]:
    return [m for s in scores for m in s.metrics if m.name == name]


def _mean_score(results: list[MetricResult]) -> float | None:
    values = [r.score for r in results if r.score is not None]
    return mean(values) if values else None


def _judge_failed(result: MetricResult) -> bool:
    return result.reason.startswith("judge failed")


def _pass_rate(results: list[MetricResult]) -> float | None:
    verdicts = [r.passed for r in results if r.passed is not None]
    return sum(verdicts) / len(verdicts) if verdicts else None


def summarize(scores: list[RunScore], traces: list[RunTrace], *, meta: dict) -> str:
    lines = [
        f"# Eval run {meta.get('run_id', '')}",
        "",
        f"- Runs: {len(scores)}  |  model: {meta.get('model', '?')}"
        f"  |  judge: {meta.get('judge', 'none')}  |  commit: {meta.get('git', '?')}",
        "- Prompts: "
        + ", ".join(f"{k} v{v}" for k, v in meta.get("prompts", {}).items()),
        f"- Pipeline cost: ${sum(t.cost_usd for t in traces):.4f}"
        f"  |  judge cost: ${meta.get('judge_cost_usd', 0.0):.4f}",
        f"- Judged scores pass at {THRESHOLD:.0%}.",
        "",
    ]

    judge_errors = [m for s in scores for m in s.metrics if _judge_failed(m)]
    if judge_errors:
        first = judge_errors[0].reason.replace("\n", " ")[:300]
        lines += [
            f"- **{len(judge_errors)} judgments failed** and are left out of the "
            f"means below. First error: {first}",
            "",
        ]

    lines += ["## By stage", ""]
    rows = []
    for stage in STAGES:
        names = sorted({m.name for s in scores for m in s.metrics if m.stage == stage})
        for name in names:
            results = _results(scores, name)
            failed = sum(_judge_failed(r) for r in results)
            errors = f" ({failed} judge errors)" if failed else ""
            if all(r.score is None for r in results):
                values = [r.value for r in results if r.value is not None]
                rows.append(
                    [stage, name, str(len(values)), f"mean {_num(mean(values))}", "-"]
                    if values
                    else [stage, name, f"0{errors}", "n/a", "n/a"]
                )
                continue
            scored = [r for r in results if r.score is not None]
            count = f"{len(scored)}{errors}"
            rows.append(
                [
                    stage,
                    name,
                    count,
                    _num(_mean_score(results)),
                    _pct(_pass_rate(results)),
                ]
            )
    lines += _table(["stage", "metric", "runs", "mean", "pass rate"], rows)

    lines += ["", "## By category", ""]
    rows = []
    for category in sorted({s.category for s in scores}):
        group = [s for s in scores if s.category == category]
        rows.append(
            [
                category,
                str(len(group)),
                _num(_mean_score(_results(group, "expected_behavior"))),
                _pct(_pass_rate(_results(group, "route_correct"))),
                _num(_mean_score(_results(group, "researcher_success"))),
                _pct(_pass_rate(_results(group, "run_completed"))),
            ]
        )
    lines += _table(
        [
            "category",
            "runs",
            "expected behavior",
            "route ok",
            "researchers ok",
            "completed",
        ],
        rows,
    )

    worst = sorted(
        (
            (m.score, s.golden_id, m.reason)
            for s in scores
            for m in s.metrics
            if m.name == "expected_behavior"
            and m.score is not None
            and m.score < THRESHOLD
        ),
    )[:_WORST_SHOWN]
    if worst:
        lines += ["", "## Weakest responses", ""]
        lines += [
            f"- **{gid}** ({score:.2f}): {reason}" for score, gid, reason in worst
        ]

    failed_runs = [t for t in traces if t.error]
    if failed_runs:
        lines += ["", "## Runs that failed", ""]
        lines += [f"- **{t.golden_id}**: {t.error}" for t in failed_runs]

    empty = [
        (t.golden_id, s.query, s.error)
        for t in traces
        for r in t.researchers
        for s in r.searches
        if s.error or not s.hits
    ]
    if empty:
        lines += ["", f"## Searches that returned nothing ({len(empty)})", ""]
        lines += [
            f"- {gid}: `{query}`" + (f" (error: {error})" if error else "")
            for gid, query, error in empty
        ]
    return "\n".join(lines) + "\n"
