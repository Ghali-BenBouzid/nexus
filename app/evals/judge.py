"""Tier 2 evaluation: LLM-as-judge for the semantic signals Tier 1 cannot see.

The deterministic checks verify citation *plumbing* (does ``[n]`` resolve, are
sources used). They cannot tell whether a claim actually follows from the
findings, whether the report answers the question, or whether it covers the
question's facets. Those are judgement calls, so each is scored by a model via a
forced ``submit_judgment`` call (the same structured-output pattern the planner
and researcher use): a 1-5 score plus a one-line reason, never free-text parsing.

Caveats worth remembering: the judge is non-deterministic, costs tokens, and
(when it is the same model that wrote the report) carries self-preference bias.
Treat its scores as a noisy *relative* signal across changes, not ground truth.
A judge that errors or returns malformed output degrades to a neutral score
rather than sinking the run.
"""

import asyncio
import logging

from pydantic import BaseModel, Field, ValidationError

from app.agents.provider import LLMProvider, LLMResponse, Message
from app.agents.schemas import Report, ResearchResult
from app.agents.tools import BaseToolSpec
from app.evals.metrics import CheckResult, EvalResult, evaluate
from app.evals.runner import Aggregate, Case, CaseScore

logger = logging.getLogger(__name__)

# >= 4 of 5 is a pass for a judged dimension; a neutral fallback (3) fails.
_PASS_THRESHOLD = 4
_NEUTRAL_SCORE = 3


class JudgmentArgs(BaseModel):
    score: int = Field(description="Quality score from 1 (worst) to 5 (best)")
    reasoning: str = Field(description="One or two sentences justifying the score")


class SubmitJudgment(BaseToolSpec):
    name = "submit_judgment"
    description = "Submit your evaluation as a 1-5 integer score and a brief reason."
    args_model = JudgmentArgs


# Each dimension is the same call shape with a different instruction; the keyword
# in caps also lets a test's fake provider dispatch per dimension.
_RELEVANCE = (
    "Judge RELEVANCE: how directly and completely does the REPORT answer the "
    "QUESTION? Penalize drift, padding, or missing the actual ask."
)
_COVERAGE = (
    "Judge COVERAGE: how well does the REPORT address the important facets of the "
    "QUESTION? Penalize a narrow report that ignores major aspects."
)
_FAITHFULNESS = (
    "Judge FAITHFULNESS: does every claim in the REPORT follow from the FINDINGS? "
    "Penalize any statement in the report not supported by the findings."
)


def _render_points(result: ResearchResult) -> str:
    blocks = [f"- {p.sub_question}\n  {p.answer}" for p in result.points]
    return "\n".join(blocks) if blocks else "(no findings)"


def _parse(response: LLMResponse) -> tuple[int, str]:
    if not response.tool_calls:
        return _NEUTRAL_SCORE, "judge returned no structured judgment"
    try:
        args = JudgmentArgs(**response.tool_calls[0].args)
    except ValidationError:
        return _NEUTRAL_SCORE, "judge returned malformed judgment"
    return max(1, min(5, args.score)), args.reasoning


async def _run_judge(
    *, provider: LLMProvider, name: str, instruction: str, content: str
) -> CheckResult:
    """One judged dimension: a forced submit_judgment call mapped to a CheckResult
    (1-5 normalized to 0-1). Resilient: any failure degrades to a neutral score so
    a flaky judge call never crashes the evaluation."""
    submit = SubmitJudgment()
    messages = [
        Message(
            role="system",
            content=(
                "You are a meticulous, skeptical evaluator of research reports. "
                f"{instruction} Score on a 1-5 integer scale, then call "
                "submit_judgment with the score and a brief reason."
            ),
        ),
        Message(role="user", content=content),
    ]
    try:
        response = await provider.generate(
            messages, tools=[submit], tool_choice=submit.name
        )
        score, reasoning = _parse(response)
    except Exception as exc:  # noqa: BLE001 -- a judge must not sink the eval
        logger.warning("judge %s failed: %s", name, exc)
        score, reasoning = _NEUTRAL_SCORE, f"judge call failed: {type(exc).__name__}"

    return CheckResult(
        name=name,
        score=(score - 1) / 4,
        passed=score >= _PASS_THRESHOLD,
        detail=f"{score}/5: {reasoning}",
    )


async def judge(
    prompt: str,
    report: Report,
    result: ResearchResult | None = None,
    *,
    provider: LLMProvider,
) -> list[CheckResult]:
    """Run the judged dimensions concurrently. Relevance and coverage need only the
    question and report; faithfulness also needs the findings, so it is added only
    when the structured ``ResearchResult`` is available."""
    qr = f"QUESTION:\n{prompt}\n\nREPORT:\n{report.content}"
    tasks = [
        _run_judge(
            provider=provider, name="relevance", instruction=_RELEVANCE, content=qr
        ),
        _run_judge(
            provider=provider,
            name="coverage_quality",
            instruction=_COVERAGE,
            content=qr,
        ),
    ]
    if result is not None:
        fr = f"FINDINGS:\n{_render_points(result)}\n\nREPORT:\n{report.content}"
        tasks.append(
            _run_judge(
                provider=provider,
                name="faithfulness",
                instruction=_FAITHFULNESS,
                content=fr,
            )
        )
    return list(await asyncio.gather(*tasks))


async def evaluate_full(
    prompt: str,
    report: Report,
    result: ResearchResult | None = None,
    *,
    provider: LLMProvider,
) -> EvalResult:
    """The complete evaluation: deterministic Tier 1 checks plus the Tier 2 judged
    dimensions, merged into one result."""
    tier1 = evaluate(report, result)
    tier2 = await judge(prompt, report, result, provider=provider)
    return EvalResult(checks=tier1.checks + tier2)


async def score_cases(cases: list[Case], *, provider: LLMProvider) -> Aggregate:
    """Score a batch of cases with the full Tier 1 + Tier 2 evaluation. A case's
    name is its prompt, which the relevance/coverage judges need."""
    scores: list[CaseScore] = []
    for case in cases:
        evaluation = await evaluate_full(
            case.name, case.report, case.result, provider=provider
        )
        scores.append(CaseScore(name=case.name, evaluation=evaluation))
    return Aggregate(scores=scores)
