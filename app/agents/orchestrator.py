import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.agents.consolidator import consolidate
from app.agents.planner import plan
from app.agents.provider import LLMProvider
from app.agents.researcher import research
from app.agents.schemas import AgentEvent, Finding, Report, ResearchResult
from app.agents.tools import Tool
from app.agents.writer import write

Emit = Callable[[AgentEvent], Awaitable[None]]
ShouldCancel = Callable[[], bool]

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """The run failed at the system level (every researcher hard-failed)."""


class OrchestratorCancelledError(OrchestratorError):
    """The run was cancelled (the user stopped it). A subclass of
    OrchestratorError so the job's existing handling resolves the status."""


async def _noop(event: AgentEvent) -> None:
    return None


def _never_cancel() -> bool:
    return False


async def run(
    prompt: str,
    *,
    provider: LLMProvider,
    tools: list[Tool],
    emit: Emit = _noop,
    should_cancel: ShouldCancel = _never_cancel,
    cap: int,
    max_iters: int,
    max_concurrency: int,
    per_researcher_timeout: float,
    retry_cap: int,
) -> tuple[Report, ResearchResult]:
    """Pure orchestrator (no DB): plan -> fan out researchers -> consolidate ->
    write. Resilient: a researcher that fails or times out becomes a reported
    gap; only an empty plan or all researchers failing is a system failure.

    Returns both the rendered ``Report`` and the structured ``ResearchResult`` it
    was written from. The ``ResearchResult`` is the durable, style-agnostic source
    of truth (points + per-point citations) the caller persists, so a report can
    be re-rendered later without re-running the research.
    """
    sub_questions = await plan(
        prompt, provider=provider, emit=emit, cap=cap, retry_cap=retry_cap
    )

    if should_cancel():
        raise OrchestratorCancelledError("research was stopped")

    total = len(sub_questions)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(index: int, sub_question: str) -> Finding:
        # Emit the lifecycle here (not in the researcher leaf): this is the only
        # place that knows the researcher's index and the total, which is what the
        # live feed needs to render "researcher k/N" honestly.
        async with semaphore:
            await emit(
                AgentEvent(
                    type="researcher_start",
                    message=f"Researching: {sub_question}",
                    data={
                        "index": index,
                        "total": total,
                        "sub_question": sub_question,
                    },
                )
            )
            finding = await asyncio.wait_for(
                research(
                    sub_question,
                    provider=provider,
                    tools=tools,
                    emit=emit,
                    should_cancel=should_cancel,
                    max_iters=max_iters,
                ),
                timeout=per_researcher_timeout,
            )
            await emit(
                AgentEvent(
                    type="researcher_done",
                    message=f"Done: {sub_question}",
                    data={
                        "index": index,
                        "total": total,
                        "sub_question": sub_question,
                        "found_info": finding.found_info,
                    },
                )
            )
            return finding

    results = await asyncio.gather(
        *(
            run_one(index, sub_question)
            for index, sub_question in enumerate(sub_questions, start=1)
        ),
        return_exceptions=True,
    )

    # Researchers bail early on cancel (each becomes a gap), so check here, before
    # spending the consolidate + write stages on a run the user already stopped.
    if should_cancel():
        raise OrchestratorCancelledError("research was stopped")

    findings: list[Finding] = []
    failed: list[str] = []
    for index, (sub_question, result) in enumerate(
        zip(sub_questions, results, strict=True), start=1
    ):
        if isinstance(result, Exception):
            failed.append(sub_question)
            # Log the real cause (type + message + traceback); the emit below is
            # only a user-facing summary and would otherwise hide why it failed.
            logger.warning(
                "researcher failed for sub-question %r: %s: %s",
                sub_question,
                type(result).__name__,
                result,
                exc_info=result,
            )
            await emit(
                AgentEvent(
                    type="researcher_failed",
                    message=f"Could not research: {sub_question}",
                    data={
                        "index": index,
                        "total": total,
                        "sub_question": sub_question,
                    },
                )
            )
        else:
            findings.append(result)

    if not findings:
        raise OrchestratorError("all researchers failed")

    research_result = consolidate(findings, failed)
    report = await write(research_result, provider=provider, emit=emit)
    return report, research_result
