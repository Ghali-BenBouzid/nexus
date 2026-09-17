import asyncio
import json
import re

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel

from app.evals.compare import compare_pair, render_comparison
from app.evals.goldens import Golden
from app.evals.trace import RunTrace

GOLDEN = Golden(
    id="g", category="current", input="Who won?", expected_behavior="x" * 30
)
_CONTESTANTS = re.compile(r"Contestants:\s*(\{.*?\n\})", re.DOTALL)


class FakeJudge(DeepEvalBaseLLM):
    """Picks the contestant whose output contains ``prefers``, or with
    ``prefers=None`` whichever it is shown first (a fully position-biased judge)."""

    def __init__(self, prefers: str | None) -> None:
        self.prefers = prefers
        self.calls = 0
        super().__init__("fake")

    def load_model(self) -> "FakeJudge":
        return self

    def get_model_name(self) -> str:
        return "fake"

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        raise NotImplementedError

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        assert schema is not None
        if schema.__name__ == "RewrittenReason":
            return schema(rewritten_reason="because")
        self.calls += 1
        shown = json.loads(_CONTESTANTS.search(prompt).group(1))["arena_test_cases"]
        names = list(shown)
        if self.prefers is None:
            winner = names[0]
        else:
            winner = next(n for n in names if self.prefers in shown[n])
        return schema(winner=winner, reason="because")


def _trace(response: str | None) -> RunTrace:
    return RunTrace(
        golden_id="g",
        input="Who won?",
        run_date="2026-09-17",
        model="m",
        route="answer",
        reply=response,
    )


def _compare(a: RunTrace, b: RunTrace, judge: FakeJudge, stage: str = "response"):
    return asyncio.run(
        compare_pair(GOLDEN, a, b, stage=stage, judge=judge, limit=asyncio.Semaphore(4))
    )


def test_a_run_wins_when_every_judgment_picks_it() -> None:
    judge = FakeJudge(prefers="GOOD")

    result = _compare(_trace("old answer"), _trace("GOOD answer"), judge)

    assert result.outcome == "b"
    assert result.agreed is True
    assert judge.calls == 2


def test_judgments_that_split_are_a_tie(monkeypatch) -> None:
    # DeepEval shuffles the contestants at random; script it so the two judgments
    # see opposite orders, and a judge that only follows position splits.
    flips = iter([False, True])

    def shuffle(items: list) -> None:
        if items and isinstance(items[0], tuple) and next(flips):  # contestants
            items.reverse()

    monkeypatch.setattr("deepeval.metrics.arena_g_eval.utils.random.shuffle", shuffle)

    result = _compare(_trace("one"), _trace("two"), FakeJudge(prefers=None))

    assert result.outcome == "tie"
    assert result.agreed is False


def test_a_missing_response_loses_without_asking_the_judge() -> None:
    judge = FakeJudge(prefers="GOOD")

    result = _compare(_trace(None), _trace("an answer"), judge)

    assert result.outcome == "b"
    assert judge.calls == 0


def test_plans_are_compared_only_when_both_runs_planned() -> None:
    result = _compare(_trace("a"), _trace("b"), FakeJudge(prefers="GOOD"), "plan")

    assert result.outcome == "skipped"


def test_the_report_leads_with_the_score_and_explains_the_losses() -> None:
    judge = FakeJudge(prefers="GOOD")
    lost = _compare(_trace("GOOD"), _trace("worse"), judge)
    won = _compare(_trace("worse"), _trace("GOOD"), judge)
    meta = {"run_id": "r", "git": "abc", "model": "m", "prompts": {"planner": 2}}

    report = render_comparison(
        [lost, won],
        meta_a=meta,
        meta_b=meta,
        stage="response",
        judge="fake",
        judge_cost_usd=0.0,
    )

    assert "**B wins 1, A wins 1, ties 0** out of 2 judged." in report
    assert "planner v2" in report
    assert report.index("## Where A was better") < report.index("## Where B was better")
