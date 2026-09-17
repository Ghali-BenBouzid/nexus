"""Score recorded runs, stage by stage.

Each metric answers one question about one stage of the pipeline:

- routing:  did the supervisor pick the right move for the message?
- plan:     is the plan relevant to the question, and will its sub-questions
            search well once each is handed to a researcher on its own?
- research: did each researcher find cited information, was what it retrieved
            relevant to its sub-question, and is its finding grounded in that?
- report:   is the report faithful to the findings, complete, detailed, concise,
            honest about gaps, and correctly cited?
- response: does the final answer do what a good answer to this golden does
            (expected behavior and facts, relevance, language, awareness of today's
            date)?
- system:   did the run finish, how long did it take and what did it cost?

The deterministic checks live in checks.py. The judged metrics are DeepEval
metrics scored by whichever judge model is passed in.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from deepeval.metrics import (
    AnswerRelevancyMetric,
    BaseMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams

from app.evals.checks import deterministic_checks
from app.evals.goldens import Golden
from app.evals.trace import MetricResult, RunScore, RunTrace

THRESHOLD = 0.7  # a judged score at or above this passes

MetricFactory = Callable[[DeepEvalBaseLLM], BaseMetric]
_P = SingleTurnParams


def _geval(
    name: str, steps: list[str], params: list[SingleTurnParams]
) -> MetricFactory:
    def make(judge: DeepEvalBaseLLM) -> BaseMetric:
        return GEval(
            name=name,
            evaluation_steps=steps,
            evaluation_params=params,
            model=judge,
            threshold=THRESHOLD,
        )

    return make


def _answer_relevancy(judge: DeepEvalBaseLLM) -> BaseMetric:
    return AnswerRelevancyMetric(model=judge, threshold=THRESHOLD)


def _faithfulness(judge: DeepEvalBaseLLM) -> BaseMetric:
    return FaithfulnessMetric(model=judge, threshold=THRESHOLD)


def _contextual_relevancy(judge: DeepEvalBaseLLM) -> BaseMetric:
    return ContextualRelevancyMetric(model=judge, threshold=THRESHOLD)


EXPECTED_BEHAVIOR = _geval(
    "expected_behavior",
    [
        "The input gives today's date and the user's message. The expected output "
        "describes what a good response does and may list facts it must contain.",
        "Judge whether the actual output does what the expected output describes, "
        "for this exact message: right interpretation, right kind of answer, right "
        "handling of false premises, ambiguity or missing information.",
        "When facts are listed, check each is present or clearly implied, and that "
        "none is contradicted.",
        "Penalize confident wrong claims and invented facts far more than omissions.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT, _P.EXPECTED_OUTPUT],
)

TEMPORAL_AWARENESS = _geval(
    "temporal_awareness",
    [
        "The input gives today's date and a question whose answer depends on the "
        "present.",
        "Check that the actual output treats information as current only when it "
        "is recent relative to today's date, and dates the time-bound facts it gives.",
        "Check that it signals when its information may be out of date instead of "
        "presenting it as the current state.",
        "Penalize heavily anchoring to the wrong year or presenting old events as "
        "the latest ones.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT],
)

PLAN_RELEVANCE = _geval(
    "plan_relevance",
    [
        "The input gives today's date and the user's question. The actual output is "
        "the list of sub-questions a planner wrote to research it.",
        "Check that every sub-question directly serves answering the user's "
        "question, with no drift to side topics.",
        "Check that together they cover the main facets a complete answer needs, "
        "and that no two ask the same thing.",
        "Penalize heavily a plan that misreads the question, such as researching "
        "the wrong entity or the wrong sense of an ambiguous word.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT],
)

PLAN_SEARCHABILITY = _geval(
    "plan_searchability",
    [
        "Each sub-question in the actual output is handed alone to a web researcher "
        "who never sees the user's question.",
        "Check that each is self-contained: it names its subject and scope and, "
        "when the question is about the present, the time frame implied by today's "
        "date in the input.",
        "Check that each is specific and answerable from web search results, not "
        "vague ('everything about X') or a matter of pure opinion.",
        "Penalize sub-questions that assume an outdated year or fact, or are "
        "phrased so that a search engine would return nothing useful.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT],
)

REPORT_COMPLETENESS = _geval(
    "report_completeness",
    [
        "The input is the user's question. The retrieval context is the verified "
        "findings the report was written from.",
        "Check that the actual output answers the question directly and early.",
        "Check that it uses the important findings rather than dropping them, and "
        "covers the facets of the question the findings support.",
        "Penalize a report that leaves the actual question unanswered while "
        "discussing related topics.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT, _P.RETRIEVAL_CONTEXT],
)

REPORT_DEPTH = _geval(
    "report_depth",
    [
        "Check whether the actual output gives specifics that answer the input: "
        "names, numbers, dates, mechanisms, examples and trade-offs.",
        "Penalize vague generalities that could be written without any research.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT],
)

REPORT_CONCISION = _geval(
    "report_concision",
    [
        "Check that the length of the actual output fits the input: a simple "
        "factual question deserves a short answer, a broad question a longer one.",
        "Penalize filler, repetition, generic preambles, hedging and restating the "
        "question.",
        "A high score means every paragraph earns its place.",
    ],
    [_P.INPUT, _P.ACTUAL_OUTPUT],
)

GAP_HONESTY = _geval(
    "gap_honesty",
    [
        "The retrieval context lists the findings and the sub-questions the "
        "research could not answer (gaps).",
        "Check that the actual output says plainly what could not be determined.",
        "Penalize heavily any content that fills a gap with facts absent from the "
        "findings.",
    ],
    [_P.ACTUAL_OUTPUT, _P.RETRIEVAL_CONTEXT],
)


@dataclass
class JudgedCase:
    name: str
    stage: str
    make_metric: MetricFactory
    test_case: LLMTestCase


def dated_input(trace: RunTrace, question: str) -> str:
    return f"Today's date: {trace.run_date}\nUser's message: {question}"


def expected_output(golden: Golden) -> str:
    text = golden.expected_behavior
    if golden.expected_facts:
        text += "\nFacts a correct response contains:\n" + "\n".join(
            f"- {fact}" for fact in golden.expected_facts
        )
    return text


def judged_cases(
    golden: Golden, trace: RunTrace
) -> tuple[list[JudgedCase], list[MetricResult]]:
    """The judged metrics that apply to this run, plus verdicts that need no judge
    (a researcher that retrieved nothing scores zero on retrieval relevance)."""
    cases: list[JudgedCase] = []
    direct: list[MetricResult] = []

    response = trace.response
    if response:
        cases.append(
            JudgedCase(
                "expected_behavior",
                "response",
                EXPECTED_BEHAVIOR,
                LLMTestCase(
                    input=dated_input(trace, golden.input),
                    actual_output=response,
                    expected_output=expected_output(golden),
                ),
            )
        )
        cases.append(
            JudgedCase(
                "response_relevancy",
                "response",
                _answer_relevancy,
                LLMTestCase(input=golden.input, actual_output=response),
            )
        )
        if golden.time_sensitive:
            cases.append(
                JudgedCase(
                    "temporal_awareness",
                    "response",
                    TEMPORAL_AWARENESS,
                    LLMTestCase(
                        input=dated_input(trace, golden.input), actual_output=response
                    ),
                )
            )

    if trace.plan:
        plan_case = LLMTestCase(
            input=dated_input(trace, trace.research_query or golden.input),
            actual_output="\n".join(
                f"{n}. {q}" for n, q in enumerate(trace.plan, start=1)
            ),
        )
        cases.append(JudgedCase("plan_relevance", "plan", PLAN_RELEVANCE, plan_case))
        cases.append(
            JudgedCase("plan_searchability", "plan", PLAN_SEARCHABILITY, plan_case)
        )

    for researcher in trace.researchers:
        evidence = researcher.evidence
        if not evidence:
            direct.append(
                MetricResult(
                    name="retrieval_relevance",
                    stage="research",
                    score=0.0,
                    passed=False,
                    reason=f"nothing retrieved for {researcher.sub_question!r}",
                )
            )
            continue
        finding = researcher.finding
        research_case = LLMTestCase(
            input=researcher.sub_question,
            actual_output=finding or "(no finding)",
            retrieval_context=evidence,
        )
        cases.append(
            JudgedCase(
                "retrieval_relevance", "research", _contextual_relevancy, research_case
            )
        )
        if finding:
            cases.append(
                JudgedCase(
                    "finding_relevance", "research", _answer_relevancy, research_case
                )
            )
            cases.append(
                JudgedCase(
                    "finding_faithfulness", "research", _faithfulness, research_case
                )
            )

    if trace.report:
        question = trace.research_query or golden.input
        if trace.consolidated:
            cases.append(
                JudgedCase(
                    "report_faithfulness",
                    "report",
                    _faithfulness,
                    LLMTestCase(
                        input=question,
                        actual_output=trace.report,
                        retrieval_context=trace.consolidated,
                    ),
                )
            )
        findings_case = LLMTestCase(
            input=question,
            actual_output=trace.report,
            retrieval_context=trace.consolidated or ["(no findings)"],
        )
        report_case = LLMTestCase(input=question, actual_output=trace.report)
        cases.append(
            JudgedCase(
                "report_completeness", "report", REPORT_COMPLETENESS, findings_case
            )
        )
        cases.append(JudgedCase("report_depth", "report", REPORT_DEPTH, report_case))
        cases.append(
            JudgedCase("report_concision", "report", REPORT_CONCISION, report_case)
        )
        if trace.gaps:
            gaps_context = [
                *trace.consolidated,
                *(f"GAP (not answered): {gap}" for gap in trace.gaps),
            ]
            cases.append(
                JudgedCase(
                    "gap_honesty",
                    "report",
                    GAP_HONESTY,
                    LLMTestCase(
                        input=question,
                        actual_output=trace.report,
                        retrieval_context=gaps_context,
                    ),
                )
            )
    return cases, direct


def collapse(results: list[MetricResult]) -> list[MetricResult]:
    """Merge per-researcher results of the same metric into one per run: the mean
    score, passing only if every researcher passed."""
    merged: dict[str, list[MetricResult]] = {}
    for result in results:
        merged.setdefault(result.name, []).append(result)
    out = []
    for name, group in merged.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        scores = [r.score for r in group if r.score is not None]
        verdicts = [r.passed for r in group if r.passed is not None]
        out.append(
            MetricResult(
                name=name,
                stage=group[0].stage,
                score=sum(scores) / len(scores) if scores else None,
                passed=all(verdicts) if verdicts else None,
                reason=" | ".join(r.reason for r in group if r.reason),
            )
        )
    return out


async def _measure(
    case: JudgedCase, judge: DeepEvalBaseLLM, limit: asyncio.Semaphore
) -> MetricResult:
    metric = case.make_metric(judge)
    async with limit:
        try:
            await metric.a_measure(case.test_case, _show_indicator=False)
        except Exception as exc:  # noqa: BLE001 -- one failed judgment is not fatal
            return MetricResult(
                name=case.name,
                stage=case.stage,
                reason=f"judge failed: {type(exc).__name__}: {exc}",
            )
    return MetricResult(
        name=case.name,
        stage=case.stage,
        score=metric.score,
        passed=metric.is_successful(),
        reason=metric.reason or "",
    )


async def score_run(
    golden: Golden,
    trace: RunTrace,
    *,
    judge: DeepEvalBaseLLM | None,
    limit: asyncio.Semaphore,
) -> RunScore:
    """Every metric for one run. Without a judge only the deterministic checks run."""
    results = deterministic_checks(golden, trace)
    if judge is not None:
        cases, direct = judged_cases(golden, trace)
        results += direct
        results += await asyncio.gather(*(_measure(c, judge, limit) for c in cases))
    return RunScore(
        golden_id=golden.id, category=golden.category, metrics=collapse(results)
    )
