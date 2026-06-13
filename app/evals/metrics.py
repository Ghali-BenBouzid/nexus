"""Tier 1 evaluation: deterministic, LLM-free checks on a research run's output.

These score the integrity of the *cited report* and the structured
``ResearchResult`` behind it. No judgement, no model call: every check is a pure
function over the artifacts, so it is fast, free, fully repeatable, and safe to
run in CI. The headline check is ``report_citation_validity``, which catches a
writer emitting a marker like ``[5]`` when only three sources exist.

Higher-level, semantic signals (faithfulness, relevance) need an LLM judge and
live in a separate Tier 2 layer; nothing here calls a provider.
"""

import re

from pydantic import BaseModel

from app.agents.schemas import Report, ResearchResult

# Citation markers are bracketed integers like [1] or [2][3]. Markdown links
# ([text](url)) never match because the bracket content is not all digits.
_MARKER = re.compile(r"\[(\d+)\]")


class CheckResult(BaseModel):
    """One deterministic check. ``score`` is 0.0 (worst) to 1.0 (perfect);
    ``passed`` is the hard pass/fail; ``offenders`` names the specific defects."""

    name: str
    score: float
    passed: bool
    detail: str
    offenders: list[str] = []


class EvalResult(BaseModel):
    """The checks run for a single research output, with convenience rollups."""

    checks: list[CheckResult]

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return sum(c.score for c in self.checks) / len(self.checks)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


def _markers(text: str) -> list[int]:
    return [int(n) for n in _MARKER.findall(text)]


def report_citation_validity(report: Report) -> CheckResult:
    """Every ``[n]`` in the prose must resolve to a real source (1..len(sources)).

    This is the check that catches the known bug: a report citing ``[5]`` when its
    source list has fewer entries. An out-of-range marker is a hard failure."""
    n_sources = len(report.sources)
    markers = _markers(report.content)
    out_of_range = sorted({m for m in markers if m < 1 or m > n_sources})
    valid = sum(1 for m in markers if 1 <= m <= n_sources)
    score = 1.0 if not markers else valid / len(markers)
    detail = (
        "no citation markers in report"
        if not markers
        else f"{valid}/{len(markers)} markers resolve to one of {n_sources} sources"
    )
    return CheckResult(
        name="report_citation_validity",
        score=score,
        passed=not out_of_range,
        detail=detail,
        offenders=[f"[{m}] out of range (1..{n_sources})" for m in out_of_range],
    )


def source_utilization(report: Report) -> CheckResult:
    """Every listed source should be cited at least once in the prose. A source
    that is listed but never referenced is dangling: the sources panel shows the
    reader something the report never actually used."""
    n = len(report.sources)
    if n == 0:
        return CheckResult(
            name="source_utilization",
            score=1.0,
            passed=True,
            detail="no sources to use",
        )
    cited = {m for m in _markers(report.content) if 1 <= m <= n}
    dangling = [i for i in range(1, n + 1) if i not in cited]
    score = (n - len(dangling)) / n
    return CheckResult(
        name="source_utilization",
        score=score,
        passed=not dangling,
        detail=f"{n - len(dangling)}/{n} sources cited in prose",
        offenders=[f"source [{i}] listed but never cited" for i in dangling],
    )


def point_grounding(result: ResearchResult) -> CheckResult:
    """The structured side of citation integrity: every ``source_ids`` value on a
    point must index a real global source. Validates the consolidator's renumber,
    independent of how the writer later renders the prose."""
    n = len(result.sources)
    ids = [(p.sub_question, sid) for p in result.points for sid in p.source_ids]
    bad = [(sq, sid) for sq, sid in ids if sid < 1 or sid > n]
    total = len(ids)
    score = 1.0 if total == 0 else (total - len(bad)) / total
    detail = (
        "no point cites any source"
        if total == 0
        else f"{total - len(bad)}/{total} point citations in range"
    )
    return CheckResult(
        name="point_grounding",
        score=score,
        passed=not bad,
        detail=detail,
        offenders=[f"{sq!r} cites [{sid}] (1..{n})" for sq, sid in bad],
    )


def coverage(result: ResearchResult) -> CheckResult:
    """Fraction of sub-questions that produced an answer rather than a gap. Gaps
    are honest reporting, not defects, so they lower the score without being
    flagged as offenders. A run with zero sub-questions scores 0 and fails."""
    answered = len(result.points)
    gaps = len(result.gaps)
    total = answered + gaps
    score = 0.0 if total == 0 else answered / total
    detail = (
        "no sub-questions in result"
        if total == 0
        else f"{answered}/{total} sub-questions answered ({gaps} gap(s))"
    )
    return CheckResult(
        name="coverage",
        score=score,
        passed=answered > 0,
        detail=detail,
    )


def evaluate(report: Report, result: ResearchResult | None = None) -> EvalResult:
    """Run the Tier 1 checks. Report-only mode covers the prose-side integrity
    (validity + utilization); passing the ``ResearchResult`` adds the structured
    checks (point grounding + coverage)."""
    checks = [report_citation_validity(report), source_utilization(report)]
    if result is not None:
        checks += [point_grounding(result), coverage(result)]
    return EvalResult(checks=checks)
