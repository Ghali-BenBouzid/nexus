import asyncio
from collections.abc import Awaitable, Callable

from app.agents.consolidator import consolidate
from app.agents.planner import plan
from app.agents.provider import LLMProvider
from app.agents.researcher import research
from app.agents.schemas import AgentEvent, Finding, Report
from app.agents.tools import Tool
from app.agents.writer import write

Emit = Callable[[AgentEvent], Awaitable[None]]

DEFAULT_CAP = 5
DEFAULT_MAX_ITERS = 5
DEFAULT_MAX_CONCURRENCY = 3
DEFAULT_PER_RESEARCHER_TIMEOUT = 120.0


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
    cap: int = DEFAULT_CAP,
    max_iters: int = DEFAULT_MAX_ITERS,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    per_researcher_timeout: float = DEFAULT_PER_RESEARCHER_TIMEOUT,
) -> Report:
    """Pure orchestrator (no DB): plan -> fan out researchers -> consolidate ->
    write. Resilient: a researcher that fails or times out becomes a reported
    gap; only an empty plan or all researchers failing is a system failure.
    """
    sub_questions = await plan(prompt, provider=provider, emit=emit, cap=cap)

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
    return await write(research_result, provider=provider, emit=emit)
