"""A research run: plan the question, research every angle at once, collect.

This is what the supervisor's ``research`` tool does, and what a deep run does
with a wider plan and a longer budget. It is deliberately not a graph: the shape
is one fan-out, which ``asyncio`` already expresses, and the only run that needs
to survive a restart (the deep one) checkpoints around this, in app.agents.deep.

Consolidating is arithmetic, not a model call, and now barely that: every agent
in a turn cites out of the same registry, so there is nothing to renumber.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from app.agents.planner import plan
from app.agents.provider import ProviderCreditsError
from app.agents.researcher import research_one
from app.agents.schemas import (
    AgentEvent,
    Claim,
    Finding,
    ResearchPoint,
    ResearchResult,
)
from app.agents.sources import Sources
from app.agents.tools import SearchBackend
from app.core.config import settings
from app.observability import stage
from app.prompts.planner import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]
# Built by the job that owns the run: billing, pacing, error mapping, the stop
# check, and a progress tag naming the agent the events come from.
Middleware = Callable[..., list]


async def _noop(event: AgentEvent) -> None:
    return None


def _no_middleware(agent: str, emit: Emit | None = None, **data: Any) -> list:
    return []


@dataclass
class Limits:
    """How wide and how long one research run may go."""

    cap: int
    max_iters: int
    searches: int  # web searches per researcher
    concurrency: int
    budget: float  # seconds before researchers stop searching and submit
    per_researcher_timeout: float  # hard stop for one researcher
    min_pages: int = 0  # pages a researcher reads before it may submit a finding

    @classmethod
    def normal(cls) -> "Limits":
        return cls(
            cap=settings.cap,
            max_iters=settings.max_iters,
            searches=settings.searches,
            concurrency=settings.max_concurrency,
            budget=settings.research_budget,
            per_researcher_timeout=settings.per_researcher_timeout,
        )

    @classmethod
    def deep(cls) -> "Limits":
        return cls(
            cap=settings.deep_cap,
            max_iters=settings.deep_max_iters,
            searches=settings.deep_searches,
            concurrency=settings.deep_concurrency,
            budget=settings.deep_research_budget,
            per_researcher_timeout=settings.deep_researcher_timeout,
            min_pages=settings.deep_min_pages,
        )


async def run_research(
    question: str,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    sources: Sources,
    emit: Emit = _noop,
    middleware: Middleware = _no_middleware,
    limits: Limits | None = None,
    planner_prompt: ChatPromptTemplate = PROMPT,
) -> ResearchResult:
    """Plan ``question``, research every sub-question at once, and collect what
    came back. Raises only if the planner produced nothing or every researcher
    hard-failed: one failed researcher is a gap in the result, not a failure."""
    limits = limits or Limits.normal()
    sub_questions = await plan(
        question,
        model=model,
        emit=emit,
        cap=limits.cap,
        retry_cap=settings.planner_retry_cap,
        prompt=planner_prompt,
    )
    findings = await research_all(
        sub_questions,
        model=model,
        backend=backend,
        emit=emit,
        middleware=middleware,
        limits=limits,
    )
    return consolidate(findings, sources)


async def research_all(
    sub_questions: list[str],
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    emit: Emit = _noop,
    middleware: Middleware = _no_middleware,
    limits: Limits | None = None,
) -> list[Finding | None]:
    """One researcher per sub-question, in parallel, in plan order. ``None`` in
    the returned list is a researcher that failed: a gap in the result rather
    than the end of the run."""
    limits = limits or Limits.normal()
    # One shared deadline, as wall-clock time so it means the same in every task.
    deadline = time.time() + limits.budget
    gate = asyncio.Semaphore(limits.concurrency)
    total = len(sub_questions)

    async def one(index: int, sub_question: str) -> Finding | None:
        async with gate:
            return await research_task(
                index,
                total,
                sub_question,
                model=model,
                backend=backend,
                emit=emit,
                middleware=middleware,
                limits=limits,
                deadline=deadline,
            )

    return list(
        await asyncio.gather(*(one(i, q) for i, q in enumerate(sub_questions, start=1)))
    )


async def research_task(
    index: int,
    total: int,
    sub_question: str,
    *,
    model: BaseChatModel,
    backend: SearchBackend,
    emit: Emit,
    middleware: Middleware,
    limits: Limits,
    deadline: float,
) -> Finding | None:
    """One researcher, with its own lifecycle events. A failure or a timeout
    becomes a gap; only running out of credits fails the run, since every other
    call would fail too."""
    lifecycle = {"index": index, "total": total, "sub_question": sub_question}
    # Names this researcher for everything under it: the usage tally and, in the
    # evals, which researcher each search belonged to.
    marker = f"research-{index}"
    own_emit = tagged(emit, index=index, total=total)
    await emit(
        AgentEvent(
            type="researcher_start",
            message=f"Researching: {sub_question}",
            data=lifecycle,
        )
    )
    try:
        with stage(marker):
            finding = await asyncio.wait_for(
                research_one(
                    sub_question,
                    model=model,
                    backend=backend,
                    middleware=middleware(
                        "researcher", own_emit, index=index, total=total
                    ),
                    emit=own_emit,
                    max_iters=limits.max_iters,
                    searches=limits.searches,
                    min_pages=limits.min_pages,
                    deadline=time.monotonic() + (deadline - time.time()),
                ),
                timeout=limits.per_researcher_timeout,
            )
    except ProviderCreditsError:
        raise
    except Exception as exc:
        # Log the real cause; the event is only a user-facing summary.
        logger.warning(
            "researcher failed for sub-question %r: %s: %s",
            sub_question,
            type(exc).__name__,
            exc,
            exc_info=exc,
        )
        await emit(
            AgentEvent(
                type="researcher_failed",
                message=f"Could not research: {sub_question}",
                data=lifecycle,
            )
        )
        return None
    await emit(
        AgentEvent(
            type="researcher_done",
            message=f"Done: {sub_question}",
            data={
                **lifecycle,
                "found_info": finding.found_info,
                # What the eval harness reads to tell "found nothing" from
                # "found things but cited none of them".
                "claims": len(finding.claims),
                "cited": sum(1 for c in finding.claims if c.source_ids),
            },
        )
    )
    return finding


def tagged(emit: Emit, **data: Any) -> Emit:
    """An emit that stamps ``data`` on every event, so what happens inside one
    researcher (its model calls, its searches) says which researcher it was. With
    researchers running at once, the live feed could not tell otherwise."""

    async def stamped(event: AgentEvent) -> None:
        await emit(event.model_copy(update={"data": {**(event.data or {}), **data}}))

    return stamped


def consolidate(
    findings: list[Finding | None],
    sources: Sources,
    *,
    failed: list[str] | None = None,
) -> ResearchResult:
    """The findings as one result, numbered out of ``sources``.

    Each finding arrives with its own source list, so merging is a remap: every
    source is registered into the run's registry, which hands back the number it
    already has for a URL another researcher also found, and each claim's ids
    are rewritten to those numbers. Passing the turn's registry is what makes a
    research run's citations continuous with the supervisor's own searches.

    A researcher that failed, came back empty, or submitted nothing usable
    becomes a gap, so the answer can be honest about what is missing.
    """
    points: list[ResearchPoint] = []
    gaps: list[str] = list(failed or [])
    for index, finding in enumerate(findings, start=1):
        if finding is None:
            gaps.append(f"Sub-question {index} could not be researched.")
            continue
        numbers = sources.register(finding.sources)
        claims = [
            Claim(
                text=claim.text,
                source_ids=_remap(claim.source_ids, numbers),
            )
            for claim in finding.claims
            if claim.text.strip()
        ]
        if not finding.found_info or not claims:
            gaps.append(finding.sub_question)
            continue
        points.append(ResearchPoint(sub_question=finding.sub_question, claims=claims))
    return ResearchResult(
        points=points,
        sources=list(sources.all),
        gaps=gaps,
        consulted_sources=list(sources.all),
    )


def _remap(local_ids: list[int], numbers: list[int]) -> list[int]:
    """A claim's own source numbers, as numbers in the run's registry."""
    out: list[int] = []
    for local in local_ids:
        if 1 <= local <= len(numbers) and numbers[local - 1] not in out:
            out.append(numbers[local - 1])
    return out


def render_findings(result: ResearchResult) -> str:
    """The findings as the report writer and the supervisor read them: every
    claim on its own line with the numbers that back it."""
    lines = ["# Research points", ""]
    for point in result.points:
        lines.append(f"## {point.sub_question}")
        for claim in point.claims:
            citations = "".join(f"[{number}]" for number in claim.source_ids)
            lines.append(f"{claim.text} {citations}".strip())
        lines.append("")

    lines.append("# Sources")
    for number, source in enumerate(result.sources, start=1):
        lines.append(f"[{number}] {source.title} - {source.url}")

    if result.gaps:
        lines += ["", "# Gaps (could not be determined)"]
        lines += [f"- {gap}" for gap in result.gaps]

    return "\n".join(lines)
