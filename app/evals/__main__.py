"""Run the eval harness.

    uv run python -m app.evals run                          # collect, then score
    uv run python -m app.evals run --category owner,current --limit 5
    uv run python -m app.evals collect --only owner-who-first-name,fact-ethanol
    uv run python -m app.evals score evals_runs/20260914-153000
    uv run python -m app.evals score evals_runs/20260914-153000 --no-judge

``collect`` runs each golden through the real pipeline, so it spends provider and
Tavily credits (one full research run per golden). ``score`` spends judge credits
unless ``--no-judge`` is given. Everything lands in ``evals_runs/<run id>/``:
meta.json, traces.jsonl, scores.jsonl and summary.md.
"""

import argparse
import asyncio
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from app.agents.search import TavilyBackend
from app.core.config import settings
from app.evals.collect import collect_one
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
        "settings": {
            "cap": settings.cap,
            "max_iters": settings.max_iters,
            "max_concurrency": settings.max_concurrency,
            "planner_retry_cap": settings.planner_retry_cap,
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


async def _score(run_dir: Path, *, use_judge: bool, concurrency: int) -> str:
    traces = _load_traces(run_dir)
    goldens = {g.id: g for g in load_goldens()}
    missing = [t.golden_id for t in traces if t.golden_id not in goldens]
    if missing:
        logger.warning("skipping traces whose golden no longer exists: %s", missing)
    traces = [t for t in traces if t.golden_id in goldens]

    judge = JudgeModel() if use_judge else None
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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.command == "score":
        print(
            asyncio.run(
                _score(
                    args.run_dir,
                    use_judge=not args.no_judge,
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
        print(asyncio.run(_score(run_dir, use_judge=not args.no_judge, concurrency=8)))


if __name__ == "__main__":
    main()
