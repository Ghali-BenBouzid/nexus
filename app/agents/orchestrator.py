import asyncio
from collections.abc import Awaitable, Callable

from app.agents.consolidator import consolidate
from app.agents.planner import plan
from app.agents.provider import LLMProvider
from app.agents.researcher import research
from app.agents.schemas import AgentEvent, Finding, Report, ResearchResult
from app.agents.tools import Tool
from app.agents.writer import write

Emit = Callable[[AgentEvent], Awaitable[None]]


class OrchestratorError(Exception):
    """The run failed at the system level (every researcher hard-failed)."""


async def _noop(event: AgentEvent) -> None:
    return None


async def run(
    prompt: str,
    *,
    provider: LLMProvider,
    tools: list[Tool],
    emit: Emit = _noop,
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

    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(sub_question: str) -> Finding:
        async with semaphore:
            return await asyncio.wait_for(
                research(
                    sub_question,
                    provider=provider,
                    tools=tools,
                    emit=emit,
                    max_iters=max_iters,
                ),
                timeout=per_researcher_timeout,
            )

    results = await asyncio.gather(
        *(run_one(sub_question) for sub_question in sub_questions),
        return_exceptions=True,
    )

    findings: list[Finding] = []
    failed: list[str] = []
    for sub_question, result in zip(sub_questions, results, strict=True):
        if isinstance(result, Exception):
            failed.append(sub_question)
            await emit(
                AgentEvent(
                    type="researcher_failed",
                    message=f"Could not research: {sub_question}",
                )
            )
        else:
            findings.append(result)

    if not findings:
        raise OrchestratorError("all researchers failed")

    research_result = consolidate(findings, failed)
    report = await write(research_result, provider=provider, emit=emit)
    return report, research_result
