"""Run goldens through the real pipeline, stage by stage, and record everything.

It drives the same stage functions and settings the production jobs use
(supervisor.decide, plan, research, consolidate, write), with the provider and
search backend wrapped in recorders. It calls the stages itself rather than the
research graph so every search is tied to the researcher that made it. The glue
it mirrors (fan-out with a concurrency limit, a per-researcher timeout, failed
researchers becoming gaps) is small and covered by the graph's own tests.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.agents import supervisor
from app.agents.consolidator import consolidate
from app.agents.planner import plan
from app.agents.researcher import research
from app.agents.schemas import AgentEvent, Finding
from app.agents.search_cache import CachingSearchBackend
from app.agents.tools import SearchBackend
from app.agents.writer import write
from app.core.config import settings
from app.evals.goldens import Golden
from app.evals.recording import RecordingSearchBackend, StageUsage
from app.evals.trace import ClaimRecord, ResearcherTrace, RunTrace, SourceRecord

logger = logging.getLogger(__name__)

# Agent events worth keeping on a researcher's trace: they explain a failure.
_NOTABLE_EVENTS = {"researcher_forced", "submit_invalid", "tool_error"}


async def collect_one(
    golden: Golden,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    until: Literal["plan"] | None = None,
) -> RunTrace:
    """Run one golden end to end, or only through planning with ``until="plan"``.
    Never raises: a failure is recorded on the trace. ``backend`` must already be
    open; each golden gets its own search cache, as each production job does."""
    usage = StageUsage()
    model.callbacks = [usage]  # every call counted, agent or not
    trace = RunTrace(
        golden_id=golden.id,
        input=golden.input,
        run_date=datetime.now(UTC).date().isoformat(),
        model=getattr(model, "model_name", "unknown"),
        until=until,
    )
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            _run(golden, trace, model, usage, CachingSearchBackend(backend)),
            timeout=settings.global_timeout,
        )
    except TimeoutError:
        trace.error = "timed out"
    except Exception as exc:  # noqa: BLE001 -- record it, never sink the suite
        logger.warning("golden %s failed", golden.id, exc_info=exc)
        trace.error = f"{type(exc).__name__}: {exc}"
    trace.seconds = round(time.monotonic() - started, 1)
    trace.usage = usage.usage
    return trace


async def _run(
    golden: Golden,
    trace: RunTrace,
    model: BaseChatModel,
    usage: StageUsage,
    backend: SearchBackend,
) -> None:
    routing_backend = RecordingSearchBackend(backend)
    try:
        decision = await supervisor.decide(
            golden.input,
            [],  # every golden is a first message: no conversation before it
            model=model,
            backend=routing_backend,
            reports=[],
            max_iters=settings.supervisor_max_iters,
        )
    finally:
        trace.supervisor_searches = routing_backend.searches
    trace.route = decision.action
    if decision.action == "answer":
        trace.reply = decision.reply
        return

    # With no earlier reports, compose has nothing to merge and the service runs
    # research on the message instead, so both routes continue here.
    query = decision.query or golden.input
    trace.research_query = query
    usage.stage = "plan"
    trace.plan = await plan(
        query, model=model, cap=settings.cap, retry_cap=settings.planner_retry_cap
    )
    if trace.until == "plan":
        return

    usage.stage = "research"
    semaphore = asyncio.Semaphore(settings.max_concurrency)
    deadline = time.monotonic() + settings.research_budget
    results = await asyncio.gather(
        *(
            _research_one(q, model, usage, backend, semaphore, deadline)
            for q in trace.plan
        )
    )
    trace.researchers = [researcher for researcher, _ in results]
    findings = [finding for _, finding in results if finding is not None]
    failed = [r.sub_question for r, finding in results if finding is None]
    if not findings:
        trace.error = "all researchers failed"
        return

    result = consolidate(findings, failed)
    trace.gaps = result.gaps
    trace.consolidated = [
        f"{point.sub_question}: {claim.text} "
        + "".join(f"[{n}]" for n in claim.source_ids)
        for point in result.points
        for claim in point.claims
    ]
    usage.stage = "write"
    report = await write(result, model=model, timeout=settings.writer_timeout)
    trace.report = report.content
    trace.sources = [SourceRecord(title=s.title, url=s.url) for s in report.sources]


async def _research_one(
    sub_question: str,
    model: BaseChatModel,
    usage: StageUsage,
    backend: SearchBackend,
    semaphore: asyncio.Semaphore,
    deadline: float,
) -> tuple[ResearcherTrace, Finding | None]:
    recorder = RecordingSearchBackend(backend)
    trace = ResearcherTrace(sub_question=sub_question)

    async def emit(event: AgentEvent) -> None:
        if event.type in _NOTABLE_EVENTS:
            trace.events.append(f"{event.type}: {event.message}")

    finding: Finding | None = None
    async with semaphore:
        started = time.monotonic()
        try:
            finding = await asyncio.wait_for(
                research(
                    sub_question,
                    model=model,
                    backend=recorder,
                    emit=emit,
                    max_iters=settings.max_iters,
                    deadline=deadline,
                ),
                timeout=settings.per_researcher_timeout,
            )
        except TimeoutError:
            trace.error = "timed out"
        except Exception as exc:  # noqa: BLE001 -- a failed researcher is a gap
            trace.error = f"{type(exc).__name__}: {exc}"
        trace.seconds = round(time.monotonic() - started, 1)

    trace.searches = recorder.searches
    trace.fetches = recorder.fetches
    if finding is not None:
        trace.found_info = finding.found_info
        trace.claims = [
            ClaimRecord(text=claim.text, source_urls=[s.url for s in claim.sources])
            for claim in finding.claims
        ]
    return trace, finding
