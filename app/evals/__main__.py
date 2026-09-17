"""Run the eval harness.

    uv run python -m app.evals run                          # collect, then score
    uv run python -m app.evals run --category owner,current --limit 5
    uv run python -m app.evals collect --only owner-who-first-name,fact-ethanol
    uv run python -m app.evals score evals_runs/20260914-153000
    uv run python -m app.evals score evals_runs/20260914-153000 --no-judge
    uv run python -m app.evals compare evals_runs/20260917-120000  # vs current code
    uv run python -m app.evals compare evals_runs/<a> evals_runs/<b> --stage plan

``collect`` runs each golden through the real pipeline, so it spends provider and
Tavily credits (one full research run per golden). ``score`` spends judge credits
unless ``--no-judge`` is given. Everything lands in ``evals_runs/<run id>/``:
meta.json, traces.jsonl, scores.jsonl and summary.md.

``compare`` judges two runs against each other, golden by golden. Given only a
baseline, it first collects the current code on the baseline's goldens (the same
cost as ``collect``), so a baseline is collected once and reused for every
candidate. The judging costs judge credits only; ``compare-<stage>.md`` lands in
the candidate's run directory.
"""

import argparse
import asyncio
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from app import prompts
from app.agents.search import TavilyBackend
from app.core.config import settings
from app.evals.collect import collect_one
from app.evals.compare import compare_pair, render_comparison
from app.evals.goldens import Golden, load_goldens
from app.evals.judge_model import JudgeModel
from app.evals.scoring import score_run
from app.evals.summary import summarize
from app.evals.trace import RunTrace
from app.research.dependencies import get_provider, get_search_backend

RUNS_ROOT = Path("evals_runs")
logger = logging.getLogger("app.evals")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _select(goldens: list[Golden], args: argparse.Namespace) -> list[Golden]:
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {g.id for g in goldens}
        if unknown:
            raise SystemExit(f"unknown golden ids: {sorted(unknown)}")
        goldens = [g for g in goldens if g.id in wanted]
    if args.category:
        categories = set(args.category.split(","))
        goldens = [g for g in goldens if g.category in categories]
    return goldens[: args.limit] if args.limit else goldens


async def _collect(goldens: list[Golden], run_dir: Path, concurrency: int) -> None:
    provider = get_provider()
    backend: TavilyBackend = get_search_backend()
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": run_dir.name,
        "started": datetime.now().isoformat(timespec="seconds"),
        "git": _git_commit(),
        "provider": settings.llm_provider,
        "model": getattr(provider, "model", "unknown"),
        "prompts": prompts.versions(),  # what a score change between runs came from
        "settings": {
            "cap": settings.cap,
            "max_iters": settings.max_iters,
            "max_concurrency": settings.max_concurrency,
            "planner_retry_cap": settings.planner_retry_cap,
            "research_budget": settings.research_budget,
            "per_researcher_timeout": settings.per_researcher_timeout,
            "global_timeout": settings.global_timeout,
        },
        "goldens": [g.id for g in goldens],
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    limit = asyncio.Semaphore(concurrency)
    done = 0
    traces_path = run_dir / "traces.jsonl"

    async def one(golden: Golden) -> None:
        nonlocal done
        async with limit:
            trace = await collect_one(golden, provider=provider, backend=backend)
        # Appended as each finishes, so an interrupted run keeps what it collected.
        with traces_path.open("a", encoding="utf-8") as out:
            out.write(trace.model_dump_json() + "\n")
        done += 1
        ok = sum(r.succeeded for r in trace.researchers)
        research = (
            f", {ok}/{len(trace.researchers)} researchers ok" if trace.plan else ""
        )
        status = f"FAILED ({trace.error})" if trace.error else trace.route
        print(
            f"[{done}/{len(goldens)}] {golden.id}: {status}{research}, "
            f"{trace.seconds:.0f}s, ${trace.cost_usd:.4f}",
            flush=True,
        )

    async with provider, backend:
        await asyncio.gather(*(one(g) for g in goldens))


def _load_traces(run_dir: Path) -> list[RunTrace]:
    path = run_dir / "traces.jsonl"
    if not path.exists():
        raise SystemExit(f"no traces in {run_dir}; run collect first")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [RunTrace.model_validate_json(line) for line in lines if line.strip()]


async def _score(run_dir: Path, *, judge: JudgeModel | None, concurrency: int) -> str:
    traces = _load_traces(run_dir)
    goldens = {g.id: g for g in load_goldens()}
    missing = [t.golden_id for t in traces if t.golden_id not in goldens]
    if missing:
        logger.warning("skipping traces whose golden no longer exists: %s", missing)
    traces = [t for t in traces if t.golden_id in goldens]

    limit = asyncio.Semaphore(concurrency)
    scores = await asyncio.gather(
        *(score_run(goldens[t.golden_id], t, judge=judge, limit=limit) for t in traces)
    )
    with (run_dir / "scores.jsonl").open("w", encoding="utf-8") as out:
        out.writelines(score.model_dump_json() + "\n" for score in scores)

    meta_path = run_dir / "meta.json"
    meta = (
        json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    )
    meta["judge"] = judge.get_model_name() if judge else "none"
    meta["judge_cost_usd"] = round(judge.cost_usd, 6) if judge else 0.0
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    summary = summarize(list(scores), traces, meta=meta)
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    return summary


def _meta(run_dir: Path) -> dict:
    path = run_dir / "meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


async def _compare(
    baseline: Path,
    candidate: Path,
    *,
    judge: JudgeModel,
    stage: str,
    concurrency: int,
) -> str:
    goldens = {g.id: g for g in load_goldens()}
    a = {t.golden_id: t for t in _load_traces(baseline)}
    b = {t.golden_id: t for t in _load_traces(candidate)}
    shared = [gid for gid in a if gid in b and gid in goldens]
    if not shared:
        raise SystemExit("the two runs share no goldens")
    limit = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(
            compare_pair(
                goldens[gid], a[gid], b[gid], stage=stage, judge=judge, limit=limit
            )
            for gid in shared
        )
    )
    report = render_comparison(
        list(results),
        meta_a=_meta(baseline),
        meta_b=_meta(candidate),
        stage=stage,
        judge=judge.get_model_name(),
        judge_cost_usd=judge.cost_usd,
    )
    (candidate / f"compare-{stage}.md").write_text(report, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.evals")
    commands = parser.add_subparsers(dest="command", required=True)

    def selection(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--only", help="comma-separated golden ids")
        sub.add_argument("--category", help="comma-separated categories")
        sub.add_argument("--limit", type=int, help="at most this many goldens")
        sub.add_argument(
            "--concurrency", type=int, default=3, help="goldens run at once"
        )

    selection(commands.add_parser("collect", help="run the pipeline, save traces"))
    run = commands.add_parser("run", help="collect, then score")
    selection(run)
    run.add_argument("--no-judge", action="store_true")
    score = commands.add_parser("score", help="score saved traces")
    score.add_argument("run_dir", type=Path)
    score.add_argument("--no-judge", action="store_true")
    score.add_argument("--concurrency", type=int, default=8, help="judge calls at once")
    compare = commands.add_parser(
        "compare", help="judge two runs against each other, golden by golden"
    )
    compare.add_argument("baseline", type=Path, help="run A")
    compare.add_argument(
        "candidate",
        type=Path,
        nargs="?",
        help="run B; left out, the current code is collected on A's goldens",
    )
    compare.add_argument("--stage", choices=["response", "plan"], default="response")
    compare.add_argument(
        "--concurrency", type=int, default=8, help="judge calls at once"
    )
    compare.add_argument(
        "--collect-concurrency", type=int, default=3, help="goldens run at once"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    # Built before anything runs, so a missing judge setting fails before a
    # collection spends provider credits, not after.
    wants_judge = args.command == "compare" or (
        args.command in ("score", "run") and not args.no_judge
    )
    try:
        judge = JudgeModel() if wants_judge else None
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None

    if args.command == "score":
        print(
            asyncio.run(
                _score(
                    args.run_dir,
                    judge=judge,
                    concurrency=args.concurrency,
                )
            )
        )
        return

    if args.command == "compare":
        assert judge is not None
        candidate = args.candidate
        if candidate is None:
            wanted = set(_meta(args.baseline).get("goldens") or [])
            if not wanted:
                wanted = {t.golden_id for t in _load_traces(args.baseline)}
            goldens = [g for g in load_goldens() if g.id in wanted]
            candidate = RUNS_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
            print(f"Collecting {len(goldens)} golden(s) into {candidate}/")
            asyncio.run(_collect(goldens, candidate, args.collect_concurrency))
        print(
            asyncio.run(
                _compare(
                    args.baseline,
                    candidate,
                    judge=judge,
                    stage=args.stage,
                    concurrency=args.concurrency,
                )
            )
        )
        return

    goldens = _select(load_goldens(), args)
    if not goldens:
        raise SystemExit("no goldens match that selection")
    run_dir = RUNS_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"Collecting {len(goldens)} golden(s) into {run_dir}/")
    asyncio.run(_collect(goldens, run_dir, args.concurrency))
    if args.command == "run":
        print(asyncio.run(_score(run_dir, judge=judge, concurrency=8)))


if __name__ == "__main__":
    main()
