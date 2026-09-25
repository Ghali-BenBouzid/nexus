"""Which model should write deep reports? Two writers, the same material, judged
side by side.

    uv run python -m app.evals.writers                      # the defaults below
    uv run python -m app.evals.writers --a z-ai/glm-5.3-flash:low \\
        --b openai/gpt-6-luna:high --queries 249,215,164

Each example is a finished deep run from the database: the question and brief
it was asked, and the curated findings its writer was given. The lead's outline
is not kept once a run completes, so one is written here, once per example, by
the lead's model following the lead's own outline rules, and cached so every
comparison sees the same one. Both writers then get identical findings, outline
and length target, exactly as write_node passes them.

Two judges from families neither writer belongs to compare each pair with
DeepEval's ArenaGEval, which hides the names and shuffles the order. Each judge
looks twice: a writer wins with that judge only when both looks pick it.

It spends provider credits: an outline per new example, two reports per
example, and eight judgments per example. Everything lands in
evals_runs/writers-<time>/: the reports, the verdicts, and summary.md.
"""

import argparse
import asyncio
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from deepeval.metrics import ArenaGEval
from deepeval.test_case import ArenaTestCase, Contestant, LLMTestCase
from deepeval.test_case import SingleTurnParams as P
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import text

from app.agents.deep import _length, deep_length
from app.agents.model import Usage
from app.agents.report import text_of, write_report
from app.agents.research import render_findings
from app.agents.schemas import AgentEvent, ResearchResult
from app.core.config import settings
from app.db.session import SessionLocal
from app.evals.judge_model import JudgeModel
from app.prompts import render
from app.prompts.common import today
from app.prompts.deep import PROMPT as LEAD
from app.research.dependencies import chat_model

RUNS_ROOT = Path("evals_runs")
OUTLINES = RUNS_ROOT / "writer-outlines.json"
# Finished deep runs with enough findings to write from, across subjects and
# both languages.
QUERIES = [249, 215, 164, 158, 141, 134, 117, 91]
JUDGES = ["anthropic/claude-sonnet-5", "google/gemini-3.8-flash"]
LOOKS = 2

_STEPS = [
    "The input is a research brief, the outline the report was asked to follow, "
    "and the numbered findings it was written from. Each actual output is a "
    "report written from those findings alone.",
    "Faithfulness first: prefer the report whose every statement is backed by "
    "the findings and whose citation numbers point to the findings that say it. "
    "An invented fact, a wrong number or a citation to a finding that does not "
    "say it is a serious flaw, worse than leaving something out.",
    "Then synthesis: prefer the report that connects findings into ideas, "
    "compares and weighs them, and draws out what they mean for the brief, over "
    "one that restates the findings one by one or source by source.",
    "Then usefulness to the reader the brief describes: it follows the outline, "
    "answers what was asked, and says plainly what stays open.",
    "Then clarity: well organised, readable prose. Length alone is not a reason "
    "to prefer one, but padding and repetition count against it.",
]

_OUTLINE_TASK = """\
The research is done. Below are the brief and the findings your researchers \
brought back. Write the outline you would hand to the writer with \
write_report, following the rules above: its few sections, ordered by what \
matters most for the brief, what each one develops and from which findings, \
and what stays open. Structure only, not length. Reply with the outline alone."""


def _contestant(spec: str) -> tuple[str, str]:
    model, _, effort = spec.partition(":")
    return model, effort or "medium"


def _as_handed(result: ResearchResult) -> ResearchResult:
    return result.model_copy(update={"sources": result.consulted_sources})


async def _examples(ids: list[int]) -> list[dict]:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text("select id, prompt, result from queries where id = any(:ids)"),
                {"ids": ids},
            )
        ).all()
    found = {row.id: row for row in rows}
    return [
        {
            "id": i,
            "brief": found[i].prompt,
            # Stored as the report left it: ``sources`` cut to what it cited,
            # while the claims still number into everything consulted, which is
            # the list the writer was handed.
            "result": _as_handed(ResearchResult.model_validate(found[i].result)),
        }
        for i in ids
        if i in found and found[i].result
    ]


async def _outline(example: dict, cache: dict) -> str:
    key = str(example["id"])
    if key not in cache:
        system, user = render(
            LEAD,
            query=f"{_OUTLINE_TASK}\n\n# Brief\n{example['brief']}\n\n"
            f"{render_findings(example['result'])}",
            today=today(),
            cap=str(settings.deep_cap),
            language="",
        )
        reply = await chat_model(effort="high").ainvoke(
            [SystemMessage(system.content or ""), HumanMessage(user.content or "")]
        )
        cache[key] = text_of(reply).strip()
        OUTLINES.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return cache[key]


async def _write(spec: str, example: dict, outline: str) -> dict:
    model_id, effort = _contestant(spec)
    spent: list[float] = []

    async def record(usage: dict) -> None:
        spent.append(usage.get("cost_usd") or 0.0)

    stripped: list[int] = []

    async def emit(event: AgentEvent) -> None:
        if event.type == "citations_sanitized":
            stripped.extend((event.data or {}).get("stripped", []))

    model = chat_model(model_id, effort)
    model.callbacks = [Usage(record)]
    started = time.monotonic()
    report = await write_report(
        example["result"],
        model=model,
        emit=emit,
        guidance=outline,
        length=_length(example["result"]),
    )
    return {
        "seconds": round(time.monotonic() - started, 1),
        "words": len(report.content.split()),
        "cost_usd": sum(spent),
        # Citations to a source the findings do not have: the writer made them up.
        "bad_citations": len(stripped),
        "content": report.content,
    }


async def _judge(
    judge: JudgeModel, example: dict, outline: str, a: str, b: str
) -> list[str]:
    material = (
        f"# Brief\n{example['brief']}\n\n# Outline\n{outline}\n\n"
        f"{render_findings(example['result'])}"
    )
    case = ArenaTestCase(
        contestants=[
            Contestant(
                name=name, test_case=LLMTestCase(input=material, actual_output=output)
            )
            for name, output in (("A", a), ("B", b))
        ]
    )

    async def look() -> str:
        metric = ArenaGEval(
            name="writer",
            evaluation_steps=_STEPS,
            evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT],
            model=judge,
        )
        try:
            return await metric.a_measure(case, _show_indicator=False)
        except Exception as exc:  # noqa: BLE001 -- one failed look is a tie
            return f"error: {type(exc).__name__}"

    return list(await asyncio.gather(*(look() for _ in range(LOOKS))))


def _verdict(looks: list[str]) -> str:
    return looks[0].lower() if len(set(looks)) == 1 and looks[0] in "AB" else "tie"


async def main(args: argparse.Namespace) -> None:
    out = RUNS_ROOT / f"writers-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    cache = json.loads(OUTLINES.read_text()) if OUTLINES.exists() else {}
    examples = await _examples([int(i) for i in args.queries.split(",")])
    judges = [JudgeModel(model=name) for name in JUDGES]

    async def one(example: dict) -> dict:
        outline = await _outline(example, cache)
        a, b = await asyncio.gather(
            _write(args.a, example, outline), _write(args.b, example, outline)
        )
        looks = await asyncio.gather(
            *(_judge(j, example, outline, a["content"], b["content"]) for j in judges)
        )
        claims = sum(len(p.claims) for p in example["result"].points)
        return {
            "id": example["id"],
            "target": deep_length(claims),
            "a": a,
            "b": b,
            "looks": dict(zip(JUDGES, looks)),
        }

    rows = await asyncio.gather(*(one(e) for e in examples))
    (out / "results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    for row in rows:
        for side in ("a", "b"):
            (out / f"{row['id']}-{side}.md").write_text(row[side]["content"])

    lines = [
        "# Writer comparison",
        "",
        f"- A: {args.a}",
        f"- B: {args.b}",
        f"- Judges: {', '.join(JUDGES)}, {LOOKS} looks each; a split is a tie",
        f"- Judging cost: ${sum(j.cost_usd for j in judges):.3f}",
        "",
        "| Run | target | A s | B s | A words | B words | A bad cites | B bad cites | "
        + " | ".join(j.split("/")[1] for j in JUDGES)
        + " |",
        "|---" * (8 + len(JUDGES)) + "|",
    ]
    tally = {j: Counter() for j in JUDGES}
    for row in rows:
        verdicts = []
        for j in JUDGES:
            v = _verdict(row["looks"][j])
            tally[j][v] += 1
            verdicts.append(f"{v} ({'/'.join(row['looks'][j])})")
        lines.append(
            f"| {row['id']} | {row['target']} | {row['a']['seconds']} | "
            f"{row['b']['seconds']} | {row['a']['words']} | {row['b']['words']} | "
            f"{row['a']['bad_citations']} | {row['b']['bad_citations']} | "
            + " | ".join(verdicts)
            + " |"
        )
    lines.append("")
    for j in JUDGES:
        t = tally[j]
        lines.append(f"- {j}: A wins {t['a']}, B wins {t['b']}, ties {t['tie']}")
    for side in ("a", "b"):
        n = len(rows) or 1
        seconds = sum(r[side]["seconds"] for r in rows) / n
        lines.append(
            f"- {side.upper()}: mean {seconds:.1f} s, "
            f"{sum(r[side]['words'] for r in rows) / n:.0f} words, "
            f"${sum(r[side]['cost_usd'] for r in rows):.4f} for all reports"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n{out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a", default="z-ai/glm-5.3-flash:low")
    parser.add_argument("--b", default="openai/gpt-6-luna:high")
    parser.add_argument("--queries", default=",".join(map(str, QUERIES)))
    asyncio.run(main(parser.parse_args()))
