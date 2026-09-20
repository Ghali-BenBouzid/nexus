"""Deterministic checks on a recorded run: no model call, free and repeatable.

These answer the questions a judge is not needed for: did the supervisor route
the message correctly, did each researcher find something it could cite, did the
searches come back empty, are the report's citations intact, is the reply in the
user's language, and what did the run cost.
"""

from app.agents.language import detect_language
from app.agents.schemas import Report, Source
from app.evals import metrics as citations
from app.evals.goldens import Golden
from app.evals.trace import MetricResult, ResearcherTrace, RunTrace

_GOOD_SEARCH_YIELD = 0.8


def route_correct(golden: Golden, trace: RunTrace) -> MetricResult | None:
    """Did the supervisor reach for research when the question needed it, and
    leave it alone when it did not? There is no router any more, so this reads
    the judgement off what it actually did."""
    if golden.expected_route == "any" or trace.error:
        return None
    actual = "research" if trace.researched else "answer"
    ok = actual == golden.expected_route
    used = ", ".join(trace.tools) or "no tools"
    return MetricResult(
        name="route_correct",
        stage="routing",
        score=float(ok),
        passed=ok,
        reason=f"expected {golden.expected_route}, got {actual} ({used})",
    )


def run_completed(trace: RunTrace) -> MetricResult:
    ok = trace.error is None and bool(trace.response.strip())
    reason = trace.error or ("" if ok else "empty response")
    return MetricResult(
        name="run_completed", stage="system", score=float(ok), passed=ok, reason=reason
    )


def _why_failed(researcher: ResearcherTrace) -> str:
    if researcher.error:
        return researcher.error
    if not researcher.searches:
        return "never searched"
    if not any(search.hits for search in researcher.searches):
        return "every search came back empty"
    # Checked before found_info: a researcher whose submission never validates
    # ends with found_info=False too, which would read as "found nothing".
    if any(event.startswith("submit_invalid") for event in researcher.events):
        return "its findings were rejected as malformed (submit_finding invalid)"
    if not researcher.found_info:
        return "reported that it found nothing"
    return "no claim cited a source"


def researcher_success(trace: RunTrace) -> MetricResult | None:
    """Did each researcher find information and back it with a source?"""
    if not trace.researchers:
        return None
    total = len(trace.researchers)
    succeeded = sum(r.succeeded for r in trace.researchers)
    failures = [
        f"{r.sub_question!r}: {_why_failed(r)}"
        for r in trace.researchers
        if not r.succeeded
    ]
    reason = f"{succeeded}/{total} researchers found cited information"
    if failures:
        reason += "; " + "; ".join(failures)
    return MetricResult(
        name="researcher_success",
        stage="research",
        score=succeeded / total,
        passed=succeeded == total,
        reason=reason,
    )


def search_yield(trace: RunTrace) -> MetricResult | None:
    """Share of the researchers' web searches that returned at least one result."""
    searches = [s for r in trace.researchers for s in r.searches]
    if not searches:
        return None
    empty = [s for s in searches if s.error or not s.hits]
    score = 1 - len(empty) / len(searches)
    reason = f"{len(searches) - len(empty)}/{len(searches)} searches returned results"
    if empty:
        reason += "; empty: " + ", ".join(repr(s.query) for s in empty)
    return MetricResult(
        name="search_yield",
        stage="research",
        score=score,
        passed=score >= _GOOD_SEARCH_YIELD,
        reason=reason,
    )


def tool_errors(trace: RunTrace) -> MetricResult | None:
    """Failed searches, failed page fetches and crashed or timed-out researchers."""
    calls = [c for r in trace.researchers for c in (*r.searches, *r.fetches)]
    errors = [c.error for c in calls if c.error]
    errors += [f"researcher: {r.error}" for r in trace.researchers if r.error]
    if not calls and not errors:
        return None
    score = max(0.0, 1 - len(errors) / max(len(calls), 1))
    reason = f"{len(errors)} error(s) over {len(calls)} tool call(s)"
    if errors:
        reason += "; " + "; ".join(errors[:3])
    return MetricResult(
        name="tool_errors",
        stage="research",
        score=score,
        passed=not errors,
        reason=reason,
    )


def citation_checks(trace: RunTrace) -> list[MetricResult]:
    """Citation integrity on whatever the user reads: the answer in the
    conversation, or the report when the run produced one."""
    if not trace.response.strip():
        return []
    report = Report(
        content=trace.response,
        sources=[Source(title=s.title, url=s.url) for s in trace.sources],
        failed_subquestions=trace.gaps,
    )
    results = []
    for check in (citations.report_citation_validity, citations.source_utilization):
        outcome = check(report)
        results.append(
            MetricResult(
                name=outcome.name,
                stage="response",
                score=outcome.score,
                passed=outcome.passed,
                reason="; ".join([outcome.detail, *outcome.offenders]),
            )
        )
    return results


def language_match(golden: Golden, trace: RunTrace) -> MetricResult | None:
    detected = detect_language(trace.response)
    if detected is None:  # too short or an unlisted language: nothing to check
        return None
    ok = detected == golden.language
    return MetricResult(
        name="language_match",
        stage="response",
        score=float(ok),
        passed=ok,
        reason=f"expected {golden.language}, detected {detected}",
    )


def measurements(trace: RunTrace) -> list[MetricResult]:
    searches = len(trace.supervisor_searches) + sum(
        len(r.searches) for r in trace.researchers
    )
    words = len(trace.response.split())
    return [
        MetricResult(name="latency_seconds", stage="system", value=trace.seconds),
        MetricResult(name="cost_usd", stage="system", value=round(trace.cost_usd, 6)),
        MetricResult(name="searches", stage="system", value=searches),
        MetricResult(name="response_words", stage="response", value=words),
    ]


def deterministic_checks(golden: Golden, trace: RunTrace) -> list[MetricResult]:
    optional = [
        route_correct(golden, trace),
        researcher_success(trace),
        search_yield(trace),
        tool_errors(trace),
        language_match(golden, trace),
    ]
    return [
        run_completed(trace),
        *[result for result in optional if result is not None],
        *citation_checks(trace),
        *measurements(trace),
    ]
