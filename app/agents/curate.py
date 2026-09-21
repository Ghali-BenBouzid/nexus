"""The curator: what the report is built from.

Researchers work one sub-question each and never see each other's findings, so
what comes back overlaps. The same fact arrives three times in different words,
and every claim drags its sources into the report's citation list. A deep run
measured 134 claims behind 215 sources: more than any report should be built
from, and more than any reader will check.

The writer cannot fix this. Its job is to write what it is given, and it is the
wrong agent to decide what to leave out: it sees the claims but not what it
would cost to drop one, and asking it to both choose and write is what produced
reports citing source [187].

So choosing is its own step, between research and writing. One call, because
the redundancy is mostly across researchers and only a global view can see it,
and the claims are short enough that all of them fit in one prompt. It returns
numbers, never text: the curator may not rewrite a claim, so nothing it does
can put words into the report that no researcher stood behind.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.language import detect_language
from app.agents.schemas import AgentEvent, ResearchPoint, ResearchResult
from app.agents.tools import SubmitSelectionArgs
from app.observability import stage, traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.curate import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

_SUBMIT = "SubmitSelectionArgs"


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("curate")
async def curate(
    result: ResearchResult,
    *,
    model: BaseChatModel,
    emit: Emit = _noop,
    cap: int,
    timeout: float | None = None,
) -> ResearchResult:
    """The findings worth reporting, renumbered.

    Never fails a run: a curator that runs out of time or returns nothing usable
    leaves the result as it was, because an uncurated report is worse than a
    curated one and far better than no report. Measured on a real run this call
    took five minutes to read 134 claims, so its own budget is not optional: the
    writer still has to be paid for out of what is left.
    """
    claims = [claim for point in result.points for claim in point.claims]
    if len(claims) <= cap:
        return result
    try:
        with stage("curate"):
            keep = await asyncio.wait_for(
                _choose(result, model, emit, cap), timeout=timeout
            )
    except TimeoutError:
        logger.warning("the curator ran out of time; reporting every finding")
        await emit(
            AgentEvent(type="curated", message="Out of time: reporting every finding")
        )
        return result
    if not keep:
        logger.warning("the curator kept nothing; reporting every finding")
        return result
    await emit(
        AgentEvent(
            type="curated",
            message=f"Kept {len(keep)} of {len(claims)} findings",
            data={"kept": len(keep), "total": len(claims)},
        )
    )
    return _pruned(result, keep)


async def _choose(
    result: ResearchResult, model: BaseChatModel, emit: Emit, cap: int
) -> set[int]:
    """The claim numbers to keep, as the model picked them. Numbers that mean
    nothing are dropped rather than trusted."""
    numbered, total = _numbered(result)
    rendered = render(
        PROMPT,
        findings=numbered,
        cap=cap,
        today=today(),
        language=detect_language(numbered) or "",
    )
    messages = [
        HumanMessage(m.content or "")
        if m.role == "user"
        else SystemMessage(m.content or "")
        for m in rendered
    ]
    await emit(
        AgentEvent(
            type="thinking",
            message="Choosing what to report",
            data={"agent": "curator"},
        )
    )
    bound = model.bind_tools([SubmitSelectionArgs], tool_choice="any")
    reply = await bound.ainvoke(messages)
    for tool_call in reply.tool_calls:
        if tool_call["name"] != _SUBMIT:
            continue
        chosen = tool_call["args"].get("keep") or []
        return {n for n in chosen if isinstance(n, int) and 1 <= n <= total}
    return set()


def _numbered(result: ResearchResult) -> tuple[str, int]:
    """The claims as the curator reads them: numbered straight through, grouped
    by the sub-question they answer. Source numbers come along because how well
    a claim is backed is part of choosing it; the source list itself does not,
    because the curator never has to look one up."""
    lines: list[str] = []
    number = 0
    for point in result.points:
        lines.append(f"## {point.sub_question}")
        for claim in point.claims:
            number += 1
            backing = ", ".join(str(sid) for sid in claim.source_ids) or "nothing"
            lines.append(f"[{number}] {claim.text} (sources: {backing})")
        lines.append("")
    return "\n".join(lines), number


def _pruned(result: ResearchResult, keep: set[int]) -> ResearchResult:
    """The result with only the kept claims, and only the sources they cite.

    Sources are renumbered from one in order of first appearance, so the report
    never cites [187] out of a list of forty. A sub-question left with nothing
    becomes a gap, which is the honest description of it.
    """
    points: list[ResearchPoint] = []
    gaps = list(result.gaps)
    number = 0
    renumbered: dict[int, int] = {}
    for point in result.points:
        kept = []
        for claim in point.claims:
            number += 1
            if number not in keep:
                continue
            ids = []
            for sid in claim.source_ids:
                # A number that indexes no source is dropped rather than
                # trusted. Claims carry ids a researcher wrote, and a run that
                # has already spent fifteen minutes must not die on one.
                if not 1 <= sid <= len(result.sources):
                    continue
                if sid not in renumbered:
                    renumbered[sid] = len(renumbered) + 1
                ids.append(renumbered[sid])
            kept.append(claim.model_copy(update={"source_ids": ids}))
        if kept:
            points.append(point.model_copy(update={"claims": kept}))
        elif point.sub_question not in gaps:
            gaps.append(point.sub_question)
    order = sorted(renumbered, key=lambda old: renumbered[old])
    sources = [result.sources[old - 1] for old in order]
    return ResearchResult(
        points=points,
        sources=sources,
        gaps=gaps,
        consulted_sources=result.consulted_sources or result.sources,
    )
