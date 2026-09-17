import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from app.agents.language import detect_language
from app.agents.provider import (
    LLMProvider,
    ProviderCreditsError,
    ProviderError,
)
from app.agents.retry import RetryPolicy, retry_async
from app.agents.schemas import AgentEvent, Report, ResearchResult, Source
from app.observability import traced_step
from app.prompts import render
from app.prompts.common import today
from app.prompts.writer import PROMPT

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]

_CITATION = re.compile(r"\[(\d+)\]")
# A comma-grouped citation the model sometimes emits despite the prompt, e.g.
# "[2, 4, 5]" or "[2,4,5]"; the renderer only understands one number per bracket.
_CITATION_GROUP = re.compile(r"\[(\d+(?:\s*,\s*\d+)+)\]")
# Fenced blocks and inline code, so a bracketed integer inside code is not treated
# as a citation. Fenced first (it may span lines); inline code stays on one line.
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)

# The writer is the final, UX-critical step: the polished prose report is the whole
# point, so retry its one LLM call generously (on top of the provider's own per-call
# retries) instead of degrading to a raw, unformatted dump. The backoff also lets a
# saturated rate-limit window refill between attempts.
_WRITER_RETRY = RetryPolicy(max_attempts=5, base_delay=2.0, max_delay=30.0)


def _is_provider_error(exc: Exception) -> bool:
    # Out of credits is final: backing off cannot bring the credits back.
    return isinstance(exc, ProviderError) and not isinstance(exc, ProviderCreditsError)


async def _noop(event: AgentEvent) -> None:
    return None


@traced_step("write")
async def write(
    result: ResearchResult,
    *,
    provider: LLMProvider,
    emit: Emit = _noop,
    guidance: str = "",
    timeout: float | None = None,
) -> Report:
    """Render a ResearchResult into a cited prose Report via one LLM call. The
    code owns the sources and their numbers; the writer only weaves prose and
    preserves the supplied [n] markers.

    Past ``timeout`` seconds (a reasoning model can think for minutes), the report
    is assembled from the findings as they are, so the research is never lost.

    ``guidance`` carries an extra instruction from the user (used when the
    supervisor composes a longer report by merging existing ones): how to shape or
    expand the report. It never licenses new facts: the writer stays grounded in
    the provided points.
    """
    if not result.points:
        return Report(
            content="No relevant information was found for this query.",
            sources=[],
            failed_subquestions=result.gaps,
        )

    await emit(AgentEvent(type="writer_start", message="Writing report"))
    messages = render(
        PROMPT,
        findings=_render(result),
        guidance=guidance.strip(),
        today=today(),
        # Detected on the findings themselves (the sub-questions and claims), not
        # the rendered scaffolding, whose headers ("# Research points") are English.
        language=detect_language(_content_text(result)) or "",
    )
    try:
        response = await asyncio.wait_for(
            retry_async(
                lambda: provider.generate(messages),
                policy=_WRITER_RETRY,
                transient=_is_provider_error,
            ),
            timeout=timeout,
        )
        text, done = response.text or "", "Report written"
    except TimeoutError:
        logger.warning("writer ran past %ss; assembling the findings", timeout)
        text, done = _findings_report(result), "Out of time: report assembled"
    await emit(AgentEvent(type="writer_done", message=done))

    # Code owns the citations, so the report's prose and its source list are
    # reconciled here rather than trusted from the model.
    content, sources, stripped = _finalize_citations(text, result.sources)
    if stripped:
        logger.warning("stripped unbacked citation markers %s", stripped)
        await emit(
            AgentEvent(
                type="citations_sanitized",
                message=f"Removed {len(stripped)} unbacked citation(s)",
                data={"stripped": stripped},
            )
        )

    return Report(
        content=content,
        sources=sources,
        failed_subquestions=result.gaps,
    )


def _finalize_citations(
    content: str, sources: list[Source]
) -> tuple[str, list[Source], list[int]]:
    """Reconcile the prose with the source list, deterministically:

    0. Split any comma-grouped marker ([2, 4, 5]) into separate ones
       ([2][4][5]), the only form the report renderer understands.
    1. Strip any ``[n]`` the writer invented that no source can back (a missing
       citation beats a fabricated one).
    2. Keep only the sources the prose actually cites and renumber them in order
       of first appearance, so the source panel matches the report (no dangling
       entries, citations read 1, 2, 3 ... down the page).

    Returns the rewritten prose, the pruned+renumbered sources, and the stripped
    out-of-range numbers (for logging/telemetry).
    """
    # Code spans/blocks are masked out first so a literal bracketed integer inside
    # code (e.g. ``arr[10]``) is never mistaken for a citation and stripped or
    # renumbered. The placeholders carry no brackets, so the citation passes skip
    # them; they are restored verbatim at the end.
    code: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        code.append(match.group(0))
        return f"\x00{len(code) - 1}\x00"

    masked = _CODE_SPAN.sub(_mask, content)

    masked = _split_citation_groups(masked)
    masked, stripped = _strip_unbacked(masked, len(sources))

    order: list[int] = []
    for match in _CITATION.finditer(masked):
        n = int(match.group(1))
        if n not in order:
            order.append(n)
    remap = {old: new for new, old in enumerate(order, start=1)}
    masked = _CITATION.sub(lambda m: f"[{remap[int(m.group(1))]}]", masked)

    content = re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], masked)

    kept = [sources[old - 1] for old in order]
    # A grounded report that happened to cite nothing would otherwise drop every
    # source and render an empty Sources panel (reads as broken). Keep the full
    # list in that case; a report with sources but no inline markers beats one with
    # neither.
    if not kept and sources:
        return content, list(sources), stripped
    return content, kept, stripped


def _split_citation_groups(content: str) -> str:
    """Rewrite a comma-grouped citation ([2, 4, 5]) into separate markers
    ([2][4][5]) so each number renders as its own citation."""

    def replace(match: re.Match[str]) -> str:
        numbers = (n.strip() for n in match.group(1).split(","))
        return "".join(f"[{n}]" for n in numbers)

    return _CITATION_GROUP.sub(replace, content)


def _strip_unbacked(content: str, n_sources: int) -> tuple[str, list[int]]:
    """Remove any ``[n]`` marker that does not resolve to a real source."""
    stripped: list[int] = []

    def replace(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= n_sources:
            return match.group(0)
        stripped.append(n)
        return ""

    return _CITATION.sub(replace, content), stripped


def _content_text(result: ResearchResult) -> str:
    """The findings' own text (sub-questions + claims), for language detection.
    Excludes the English render scaffolding so detection sees the real content."""
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
    """A plain report straight from the findings, for when the writer model runs
    out of time: every claim keeps its citations, so nothing is lost."""
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


def _render(result: ResearchResult) -> str:
    lines = ["# Research points", ""]
    for point in result.points:
        lines.append(f"## {point.sub_question}")
        # Render claim by claim so each statement carries its own citations,
        # giving the writer claim-level attribution to preserve in the prose.
        for claim in point.claims:
            citations = "".join(f"[{number}]" for number in claim.source_ids)
            lines.append(f"{claim.text} {citations}".strip())
        lines.append("")

    lines.append("# Sources")
    for number, source in enumerate(result.sources, start=1):
        lines.append(f"[{number}] {source.title} - {source.url}")

    if result.gaps:
        lines.append("")
        lines.append("# Gaps (could not be determined)")
        lines.extend(f"- {gap}" for gap in result.gaps)

    return "\n".join(lines)
