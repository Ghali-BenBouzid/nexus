from typing import Any

from pydantic import BaseModel


class Source(BaseModel):
    title: str
    url: str


class FindingClaim(BaseModel):
    """One statement in a researcher's answer and the sources backing that
    statement. Source attribution is per claim, not per whole answer, so a
    citation maps to the specific sentence it supports."""

    text: str
    sources: list[Source] = []  # the sources backing this claim -> drive [n]


class Finding(BaseModel):
    sub_question: str
    claims: list[FindingClaim] = []
    consulted_sources: list[Source] = []  # everything fetched -> provenance/audit
    found_info: bool = True

    @property
    def answer(self) -> str:
        """The full answer text, claims joined back into prose."""
        return " ".join(claim.text for claim in self.claims)

    @property
    def cited_sources(self) -> list[Source]:
        """Every source any claim cites, deduped by url (the answer-level view)."""
        seen: set[str] = set()
        out: list[Source] = []
        for claim in self.claims:
            for source in claim.sources:
                if source.url not in seen:
                    seen.add(source.url)
                    out.append(source)
        return out


class AgentEvent(BaseModel):
    """A minimal progress event emitted while agents work. Stable ``type`` +
    human ``message`` for a basic feed now; open ``data`` for later."""

    type: str
    message: str
    data: dict[str, Any] | None = None


class Claim(BaseModel):
    """One statement in a point's answer and the global source numbers backing
    it (the consolidated, renumbered counterpart of a FindingClaim)."""

    text: str
    source_ids: list[int] = []  # 1-based citation numbers into ResearchResult.sources


class ResearchPoint(BaseModel):
    sub_question: str
    claims: list[Claim] = []

    @property
    def answer(self) -> str:
        return " ".join(claim.text for claim in self.claims)

    @property
    def source_ids(self) -> list[int]:
        """The point-level union of every claim's source numbers, in order."""
        seen: list[int] = []
        for claim in self.claims:
            for sid in claim.source_ids:
                if sid not in seen:
                    seen.append(sid)
        return seen


class ResearchResult(BaseModel):
    """The deterministic, style-agnostic artifact the consolidator produces: one
    global, deduped, numbered source list and the per-point citation mapping."""

    points: list[ResearchPoint]
    sources: list[Source]  # global, deduped; citation n -> sources[n - 1]
    gaps: list[str]
    # provenance/audit: every source any researcher looked at (deduped by url),
    # cited or not. Superset of ``sources``; hidden by default in the UI.
    consulted_sources: list[Source] = []


class Report(BaseModel):
    content: str
    sources: list[Source]
    failed_subquestions: list[str]
