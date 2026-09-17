"""Pairwise comparison of two saved runs: for each golden both ran, which one did
better?

Scoring each run on its own answers "how good is this?", and a small prompt
change often moves those averages less than the judge's own noise. Asking the
judge to pick between the two outputs for the same message is a sharper test.

The judge is DeepEval's ArenaGEval. It hides which run wrote which output and
shows them in a random order, but it always names a winner, so one call on a
close pair is close to a coin flip. Each pair is judged twice: a run wins only
when both judgments pick it, and a split is a tie.
"""

import asyncio
from collections import Counter
from typing import Literal

from deepeval.metrics import ArenaGEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import ArenaTestCase, Contestant, LLMTestCase
from deepeval.test_case import SingleTurnParams as P
from pydantic import BaseModel

from app.evals.goldens import Golden
from app.evals.scoring import dated_input, expected_output
from app.evals.trace import RunTrace

Stage = Literal["response", "plan"]
Outcome = Literal["a", "b", "tie", "skipped", "error"]
JUDGMENTS = 2

_STEPS: dict[str, list[str]] = {
    "response": [
        "The input gives today's date and the user's message. The expected output "
        "describes what a good response does and may list facts it must contain.",
        "Prefer the actual output that does what the expected output describes for "
        "this exact message and contains the listed facts.",
        "Prefer the one that is current relative to today's date: presenting old "
        "information as the latest is a serious flaw.",
        "Penalize invented facts and confident wrong claims far more than omissions.",
        "Length alone is not a reason to prefer one.",
    ],
    "plan": [
        "The input gives today's date and the user's message. Each actual output is "
        "a research plan whose sub-questions are handed alone to a web researcher "
        "who never sees the message.",
        "Prefer the plan that covers what a complete answer needs, with no drift to "
        "side topics and no two sub-questions asking the same thing.",
        "Prefer self-contained sub-questions that name their subject, scope and, for "
        "questions about the present, a time frame consistent with today's date.",
        "Prefer sub-questions specific enough that a web search returns something "
        "useful.",
    ],
}


class PairResult(BaseModel):
    golden_id: str
    category: str
    outcome: Outcome
    reasons: list[str] = []  # one per judgment
    # Whether the judgments picked the same run. Often false means the pairs are
    # close, or the judge is swayed by the order it saw them in.
    agreed: bool | None = None


def _output(trace: RunTrace, stage: Stage) -> str:
    if stage == "plan":
        return "\n".join(f"{n}. {q}" for n, q in enumerate(trace.plan, start=1))
    return trace.response


def _metric(stage: Stage, judge: DeepEvalBaseLLM) -> ArenaGEval:
    return ArenaGEval(
        name=f"pairwise_{stage}",
        evaluation_steps=_STEPS[stage],
        evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT, P.EXPECTED_OUTPUT],
        model=judge,
    )


async def compare_pair(
    golden: Golden,
    a: RunTrace,
    b: RunTrace,
    *,
    stage: Stage,
    judge: DeepEvalBaseLLM,
    limit: asyncio.Semaphore,
) -> PairResult:
    result = PairResult(golden_id=golden.id, category=golden.category, outcome="tie")
    out_a, out_b = _output(a, stage), _output(b, stage)
    if not out_a or not out_b:
        if stage == "plan" or (not out_a and not out_b):
            # A plan only exists on the research route: nothing to compare.
            return result.model_copy(update={"outcome": "skipped"})
        missing = "A" if not out_a else "B"
        return result.model_copy(
            update={
                "outcome": "b" if missing == "A" else "a",
                "reasons": [f"run {missing} produced no response"],
            }
        )

    # Both contestants need the same input: the later run date, so a run from
    # yesterday is not judged as stale.
    dated = dated_input(max(a, b, key=lambda t: t.run_date), golden.input)
    case = ArenaTestCase(
        contestants=[
            Contestant(
                name=name,
                test_case=LLMTestCase(
                    input=dated,
                    actual_output=output,
                    expected_output=expected_output(golden),
                ),
            )
            for name, output in (("A", out_a), ("B", out_b))
        ]
    )

    async def judge_once() -> tuple[str, str]:
        metric = _metric(stage, judge)
        async with limit:
            winner = await metric.a_measure(case, _show_indicator=False)
        return winner, metric.reason or ""

    try:
        verdicts = await asyncio.gather(*(judge_once() for _ in range(JUDGMENTS)))
    except Exception as exc:  # noqa: BLE001 -- one failed judgment is not fatal
        return result.model_copy(
            update={"outcome": "error", "reasons": [f"{type(exc).__name__}: {exc}"]}
        )

    winners = {winner for winner, _ in verdicts}
    agreed = len(winners) == 1
    return result.model_copy(
        update={
            "outcome": winners.pop().lower() if agreed else "tie",
            "reasons": [reason for _, reason in verdicts],
            "agreed": agreed,
        }
    )


def _describe(meta: dict) -> str:
    prompts = ", ".join(f"{k} v{v}" for k, v in meta.get("prompts", {}).items())
    return (
        f"{meta.get('run_id', '?')} (commit {meta.get('git', '?')}, "
        f"model {meta.get('model', '?')}, prompts: {prompts or 'unrecorded'})"
    )


def render_comparison(
    results: list[PairResult],
    *,
    meta_a: dict,
    meta_b: dict,
    stage: Stage,
    judge: str,
    judge_cost_usd: float,
) -> str:
    counts = Counter(r.outcome for r in results)
    judged = counts["a"] + counts["b"] + counts["tie"]
    lines = [
        f"# Pairwise comparison: {stage}",
        "",
        f"- A: {_describe(meta_a)}",
        f"- B: {_describe(meta_b)}",
        f"- Judge: {judge} with DeepEval ArenaGEval, {JUDGMENTS} judgments per pair "
        f"(${judge_cost_usd:.4f})",
        "",
        f"**B wins {counts['b']}, A wins {counts['a']}, ties {counts['tie']}** "
        f"out of {judged} judged.",
    ]
    agreement = [r.agreed for r in results if r.agreed is not None]
    if agreement:
        lines.append(
            f"The judgments agreed on {sum(agreement)} of {len(agreement)} pairs; "
            "a split counts as a tie."
        )
    if counts["skipped"] or counts["error"]:
        lines.append(
            f"Not judged: {counts['skipped']} skipped (nothing to compare), "
            f"{counts['error']} judge errors."
        )

    by_category: dict[str, Counter] = {}
    for r in results:
        by_category.setdefault(r.category, Counter())[r.outcome] += 1
    lines += ["", "| Category | B wins | A wins | Ties |", "| --- | --- | --- | --- |"]
    lines += [
        f"| {category} | {c['b']} | {c['a']} | {c['tie']} |"
        for category, c in sorted(by_category.items())
    ]

    # A's wins first: they are what a candidate B has to explain.
    for outcome, title in (
        ("a", "Where A was better"),
        ("b", "Where B was better"),
        ("error", "Judge errors"),
    ):
        group = [r for r in results if r.outcome == outcome]
        if not group:
            continue
        lines += ["", f"## {title}", ""]
        for r in group:
            lines.append(f"- **{r.golden_id}** ({r.category})")
            lines.extend(f"  - {reason}" for reason in r.reasons)
    return "\n".join(lines) + "\n"
