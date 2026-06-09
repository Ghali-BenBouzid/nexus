from collections.abc import Awaitable, Callable

from app.agents.provider import LLMProvider, Message
from app.agents.schemas import AgentEvent, Report, ResearchResult

Emit = Callable[[AgentEvent], Awaitable[None]]

_SYSTEM_PROMPT = (
    "You are a research report writer. You are given researched points, each with "
    "an answer and the citation numbers that support it, plus a numbered list of "
    "sources. Write a clear, coherent report that synthesizes the points. Cite "
    "claims using the provided bracketed numbers like [1] or [2][3]; only use the "
    "numbers given. Do not introduce facts or sources beyond those provided. If "
    "there are gaps, briefly note what could not be determined."
)


async def _noop(event: AgentEvent) -> None:
    return None


async def write(
    result: ResearchResult,
    *,
    provider: LLMProvider,
    emit: Emit = _noop,
) -> Report:
    """Render a ResearchResult into a cited prose Report via one LLM call. The
    code owns the sources and their numbers; the writer only weaves prose and
    preserves the supplied [n] markers."""
    if not result.points:
        return Report(
            content="No relevant information was found for this query.",
            sources=[],
            failed_subquestions=result.gaps,
        )

    await emit(AgentEvent(type="writer_start", message="Writing report"))
    messages = [
        Message(role="system", content=_SYSTEM_PROMPT),
        Message(role="user", content=_render(result)),
    ]
    response = await provider.generate(messages)
    await emit(AgentEvent(type="writer_done", message="Report written"))

    return Report(
        content=response.text or "",
        sources=result.sources,
        failed_subquestions=result.gaps,
    )


def _render(result: ResearchResult) -> str:
    lines = ["# Research points", ""]
    for point in result.points:
        citations = "".join(f"[{number}]" for number in point.source_ids)
        lines.append(f"## {point.sub_question}")
        lines.append(f"{point.answer} {citations}".strip())
        lines.append("")

    lines.append("# Sources")
    for number, source in enumerate(result.sources, start=1):
        lines.append(f"[{number}] {source.title} - {source.url}")

    if result.gaps:
        lines.append("")
        lines.append("# Gaps (could not be determined)")
        lines.extend(f"- {gap}" for gap in result.gaps)

    return "\n".join(lines)
