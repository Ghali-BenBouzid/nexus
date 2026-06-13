"""Live eval runner: run the real pipeline over the curated prompts and score it.

This is an offline measurement tool, not a CI test: it drives the configured
provider (Gemini) and Tavily over real network calls, so it costs quota and time.
It mirrors the background job's wiring exactly (same provider/backend/tools and
the same settings knobs), runs each prompt under the global timeout, scores the
output with the Tier 1 checks, and writes each report to disk for manual reading.

Run it with::

    uv run python -m app.evals.live

A prompt whose run fails (all researchers down, or a timeout) is recorded as a
failure rather than sinking the whole suite.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.agents import orchestrator
from app.agents.provider import LLMProvider
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import FetchPage, SearchBackend, Tool, WebSearch
from app.core.config import settings
from app.evals.cases import EVAL_PROMPTS
from app.evals.judge import score_cases
from app.evals.runner import Case, format_aggregate, run_cases
from app.research.dependencies import get_provider, get_search_backend

logger = logging.getLogger(__name__)

_OUTPUT_ROOT = Path("evals_runs")


async def run_suite(
    prompts: list[str],
    *,
    provider: LLMProvider,
    tools: list[Tool],
    cap: int,
    max_iters: int,
    max_concurrency: int,
    per_researcher_timeout: float,
    retry_cap: int,
    global_timeout: float,
) -> tuple[list[Case], list[tuple[str, str]]]:
    """Run each prompt through the orchestrator (under the global timeout) and
    build a scored Case from its output. Returns the successful cases plus a list
    of ``(prompt, error)`` for runs that failed, so one bad prompt never aborts
    the suite."""
    cases: list[Case] = []
    failures: list[tuple[str, str]] = []
    for prompt in prompts:
        try:
            report, result = await asyncio.wait_for(
                orchestrator.run(
                    prompt,
                    provider=provider,
                    tools=tools,
                    cap=cap,
                    max_iters=max_iters,
                    max_concurrency=max_concurrency,
                    per_researcher_timeout=per_researcher_timeout,
                    retry_cap=retry_cap,
                ),
                timeout=global_timeout,
            )
            cases.append(Case(name=prompt, report=report, result=result))
        except Exception as exc:  # noqa: BLE001 -- record, don't abort the suite
            logger.warning("eval run failed for %r: %s", prompt, exc)
            failures.append((prompt, f"{type(exc).__name__}: {exc}"))
    return cases, failures


def _write_reports(cases: list[Case]) -> Path:
    """Dump each rendered report (and its sources) to a timestamped directory so
    the prose can be read alongside the scores."""
    out = _OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(cases, start=1):
        lines = [f"# {case.name}", "", case.report.content, "", "## Sources"]
        lines += [
            f"{n}. {s.title} - {s.url}"
            for n, s in enumerate(case.report.sources, start=1)
        ]
        (out / f"{i:02d}.md").write_text("\n".join(lines), encoding="utf-8")
    return out


async def _amain(*, use_judge: bool) -> None:
    provider = get_provider()
    backend: SearchBackend = CachingSearchBackend(get_search_backend())
    async with provider, backend:
        tools = [WebSearch(backend=backend), FetchPage(backend=backend)]
        cases, failures = await run_suite(
            EVAL_PROMPTS,
            provider=provider,
            tools=tools,
            cap=settings.cap,
            max_iters=settings.max_iters,
            max_concurrency=settings.max_concurrency,
            per_researcher_timeout=settings.per_researcher_timeout,
            retry_cap=settings.planner_retry_cap,
            global_timeout=settings.global_timeout,
        )
        # Tier 2 judging calls the provider, so it must run while it is still open.
        aggregate = (
            await score_cases(cases, provider=provider)
            if use_judge
            else run_cases(cases)
        )
    print(format_aggregate(aggregate))
    if failures:
        print("\nRuns that failed (not scored):")
        for prompt, error in failures:
            print(f"    [ERROR] {prompt}\n        {error}")
    if cases:
        out = _write_reports(cases)
        print(f"\nReports written to {out}/")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Tier 2 judging is on by default; --no-judge runs Tier 1 only to save quota.
    use_judge = "--no-judge" not in sys.argv
    asyncio.run(_amain(use_judge=use_judge))


if __name__ == "__main__":
    main()
