"""Turning a finished research run into the report a user reads.

Not an agent: there is nothing to decide by this point and no tool to call. The
research is done, the sources are numbered, and this is one model call whose
whole job is voice and structure. The house style it writes in is the same one
the supervisor answers in (app.prompts.style), so a report and a chat reply read
as the same product.

Past its timeout the report is assembled straight from the findings, citations
intact, so minutes of research are never lost to a slow model.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.citations import finalize
from app.agents.language import detect_language
from app.agents.research import render_findings
from app.agents.schemas import AgentEvent, Report, ResearchResult
from app.observability import stage, traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.report import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("write")
async def write_report(
    result: ResearchResult,
    *,
    model: BaseChatModel,
    emit: Emit = _noop,
    guidance: str = "",
    timeout: float | None = None,
) -> Report:
    """Render a ResearchResult into a cited prose Report with one model call."""
    if not result.points:
        return Report(
            content="No relevant information was found for this query.",
            sources=[],
            failed_subquestions=result.gaps,
        )

    await emit(AgentEvent(type="writer_start", message="Writing report"))
    # The live feed shows who is waiting on the model; a plain call says so itself.
    await emit(
        AgentEvent(
            type="thinking", message="Writing the report", data={"agent": "writer"}
        )
    )
    messages = render(
        PROMPT,
        findings=render_findings(result),
        guidance=guidance.strip(),
        today=today(),
        # Detected on the findings themselves (the sub-questions and claims), not
        # the rendered scaffolding, whose headers ("# Research points") are English.
        language=detect_language(_content_text(result)) or "",
    )
    chat = [
        HumanMessage(m.content or "")
        if m.role == "user"
        else SystemMessage(m.content or "")
        for m in messages
    ]
    try:
        with stage("write"):
            response = await asyncio.wait_for(model.ainvoke(chat), timeout=timeout)
        text, done = text_of(response), "Report written"
    except TimeoutError:
        logger.warning("the report ran past %ss; assembling the findings", timeout)
        text, done = _findings_report(result), "Out of time: report assembled"
    await emit(AgentEvent(type="writer_done", message=done))

    content, sources, stripped = finalize(text, result.sources)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
        await emit(
            AgentEvent(
                type="citations_sanitized",
                message=f"Removed {len(stripped)} unbacked citation(s)",
                data={"stripped": stripped},
            )
        )
    return Report(content=content, sources=sources, failed_subquestions=result.gaps)


def as_stored(result: ResearchResult, report: Report) -> ResearchResult:
    """The result as it is saved next to its report.

    ``sources`` becomes the list the report actually cites, because that is what
    the reader sees numbered beside the text. The full consulted list stays for
    provenance, and the points keep the numbering the writer was handed, which
    indexes ``consulted_sources``: a record of what the research produced, not a
    second copy of the report's citations.
    """
    return result.model_copy(update={"sources": report.sources})


def text_of(response: object) -> str:
    """The reply's text. A model may answer in content blocks rather than one
    string, and the text assembled from those blocks reads the same."""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    parts = [
        block.get("text", "")
        for block in content or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def _content_text(result: ResearchResult) -> str:
    """The findings' own text, for language detection. Excludes the English
    render scaffolding so detection sees the real content."""
    parts: list[str] = []
    for point in result.points:
        parts.append(point.sub_question)
        parts.extend(claim.text for claim in point.claims)
    return " ".join(parts)


_OUT_OF_TIME_NOTE = {
    "English": "The writer ran out of time, so these are the findings as the "
    "researchers reported them.",
    "French": "Le rédacteur a manqué de temps : voici les résultats tels que "
    "les chercheurs les ont rapportés.",
}


def _findings_report(result: ResearchResult) -> str:
    """A plain report straight from the findings, for when the model runs out of
    time: every claim keeps its citations, so nothing is lost."""
    language = detect_language(_content_text(result)) or "English"
    note = _OUT_OF_TIME_NOTE.get(language, _OUT_OF_TIME_NOTE["English"])
    lines = [f"*{note}*", ""]
    for point in result.points:
        lines += [f"## {point.sub_question}", ""]
        for claim in point.claims:
            citations = "".join(f"[{number}]" for number in claim.source_ids)
            lines.append(f"- {claim.text}{citations}")
        lines.append("")
    return "\n".join(lines).strip()
