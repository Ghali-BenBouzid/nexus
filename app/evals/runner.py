"""Run the Tier 1 checks over a set of cases and roll the scores up.

A ``Case`` pairs a name with one research output (the ``Report`` and, when
available, the ``ResearchResult`` behind it). ``run_cases`` evaluates each and
``format_aggregate`` renders a compact text summary: per-check mean score across
the suite, plus the overall pass rate. This is the layer a curated-query live
runner or a CI gate calls; the cases themselves come from either recorded
pipeline outputs or a live run.
"""

from pydantic import BaseModel

from app.agents.schemas import Report, ResearchResult
from app.evals.metrics import EvalResult, evaluate


class Case(BaseModel):
    name: str
    report: Report
    result: ResearchResult | None = None


class CaseScore(BaseModel):
    name: str
    evaluation: EvalResult


class Aggregate(BaseModel):
    scores: list[CaseScore]

    @property
    def pass_rate(self) -> float:
        if not self.scores:
            return 0.0
        passed = sum(1 for s in self.scores if s.evaluation.passed)
        return passed / len(self.scores)

    @property
    def mean_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.evaluation.score for s in self.scores) / len(self.scores)

    def mean_by_check(self) -> dict[str, float]:
        """Average score per check name across every case that ran it."""
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for case in self.scores:
            for check in case.evaluation.checks:
                totals[check.name] = totals.get(check.name, 0.0) + check.score
                counts[check.name] = counts.get(check.name, 0) + 1
        return {name: totals[name] / counts[name] for name in totals}


def run_cases(cases: list[Case]) -> Aggregate:
    return Aggregate(
        scores=[
            CaseScore(name=c.name, evaluation=evaluate(c.report, c.result))
            for c in cases
        ]
    )


def format_aggregate(aggregate: Aggregate) -> str:
    """Render a compact report: a line per case with its failures, then the
    per-check means and the overall pass rate."""
    lines: list[str] = []
    for case in aggregate.scores:
        mark = "PASS" if case.evaluation.passed else "FAIL"
        lines.append(f"[{mark}] {case.name}  score={case.evaluation.score:.2f}")
        for failure in case.evaluation.failures:
            lines.append(f"    - {failure.name}: {failure.detail}")
            lines.extend(f"        {o}" for o in failure.offenders)

    lines.append("")
    lines.append("Per-check mean:")
    for name, score in sorted(aggregate.mean_by_check().items()):
        lines.append(f"    {name:<28} {score:.2f}")
    lines.append("")
    lines.append(
        f"Pass rate: {aggregate.pass_rate:.0%}  "
        f"Mean score: {aggregate.mean_score:.2f}  "
        f"({len(aggregate.scores)} case(s))"
    )
    return "\n".join(lines)
