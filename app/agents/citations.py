"""Reconciling what was written with what was actually retrieved.

Every text a user sees goes through here: the supervisor's chat reply, a
research report, a fact-check report. The model weaves the prose and keeps the
[n] markers it was handed; code decides which markers are real, which sources
survive, and what they are numbered. A missing citation beats a fabricated one.
"""

import re

from app.agents.schemas import Source

_CITATION = re.compile(r"\[(\d+)\]")
# A comma-grouped citation the model sometimes emits despite the prompt, e.g.
# "[2, 4, 5]" or "[2,4,5]"; the renderer only understands one number per bracket.
_CITATION_GROUP = re.compile(r"\[(\d+(?:\s*,\s*\d+)+)\]")
# Fenced blocks and inline code, so a bracketed integer inside code is not treated
# as a citation. Fenced first (it may span lines); inline code stays on one line.
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)


def finalize(
    content: str, sources: list[Source], *, keep_uncited: bool = True
) -> tuple[str, list[Source], list[int]]:
    """Reconcile the prose with the source list, deterministically:

    0. Split any comma-grouped marker ([2, 4, 5]) into separate ones
       ([2][4][5]), the only form the renderer understands.
    1. Strip any ``[n]`` that no source can back.
    2. Keep only the sources the prose cites and renumber them in order of first
       appearance, so the source panel matches the text and citations read
       1, 2, 3 down the page.

    Returns the rewritten prose, the pruned and renumbered sources, and the
    numbers that were stripped (for logging).

    ``keep_uncited``: when the prose cites nothing at all, keep the full source
    list rather than emptying the panel. True for a report, whose sources are
    the point; False for a chat reply, where an uncited answer should not drag a
    source list behind it.
    """
    # Code spans are masked first so a literal bracketed integer inside code
    # (``arr[10]``) is never mistaken for a citation. The placeholders carry no
    # brackets, so the citation passes skip them; they are restored at the end.
    code: list[str] = []

    def mask(match: re.Match[str]) -> str:
        code.append(match.group(0))
        return f"\x00{len(code) - 1}\x00"

    masked = _CODE_SPAN.sub(mask, content)
    masked = _split_groups(masked)
    masked, stripped = _strip_unbacked(masked, len(sources))

    order: list[int] = []
    for match in _CITATION.finditer(masked):
        number = int(match.group(1))
        if number not in order:
            order.append(number)
    remap = {old: new for new, old in enumerate(order, start=1)}
    masked = _CITATION.sub(lambda m: f"[{remap[int(m.group(1))]}]", masked)

    content = re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], masked)

    kept = [sources[old - 1] for old in order]
    if not kept and sources and keep_uncited:
        return content, list(sources), stripped
    return content, kept, stripped


def _split_groups(content: str) -> str:
    """Rewrite a comma-grouped citation ([2, 4, 5]) into separate markers."""

    def replace(match: re.Match[str]) -> str:
        numbers = (n.strip() for n in match.group(1).split(","))
        return "".join(f"[{n}]" for n in numbers)

    return _CITATION_GROUP.sub(replace, content)


def _strip_unbacked(content: str, n_sources: int) -> tuple[str, list[int]]:
    """Remove any ``[n]`` marker that does not resolve to a real source."""
    stripped: list[int] = []

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= n_sources:
            return match.group(0)
        stripped.append(number)
        return ""

    return _CITATION.sub(replace, content), stripped
