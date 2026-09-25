from typing import Any, Literal

from pydantic import BaseModel


class Source(BaseModel):
    title: str
    url: str


class Claim(BaseModel):
    """One statement and the 1-based numbers of the sources backing it.

    The numbers index whichever source list the claim travels with: its own
    ``Finding.sources`` inside a researcher, and ``ResearchResult.sources`` once
    the findings have been merged. Code assigns them in both cases, so a claim
    can only cite something that was really retrieved, and attribution is per
    claim rather than per answer.
    """

    text: str
    source_ids: list[int] = []


class Finding(BaseModel):
    """What one researcher came back with. It carries its own sources so it is
    plain, self-contained data: it survives a checkpoint and can be merged into
    any run's numbering later."""

    sub_question: str
    claims: list[Claim] = []
    sources: list[Source] = []  # claim.source_ids are 1-based into this list
    found_info: bool = True

    @property
    def answer(self) -> str:
        return " ".join(claim.text for claim in self.claims)


class Turn(BaseModel):
    """One earlier message of the conversation, as the agents see it: the user's
    own words, or what the assistant replied."""

    role: Literal["user", "assistant"]
    content: str
    # On an assistant turn that ended by asking: its questions, each a dict of
    # question and options, so a typed "2" can be read against them.
    ask: list[dict] | None = None


class AgentEvent(BaseModel):
    """A progress event emitted while agents work. Stable ``type`` + human
    ``message``; ``data`` carries who emitted it, so the live feed can nest a
    sub-agent's steps under the tool call that started it."""

    type: str
    message: str
    data: dict[str, Any] | None = None


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
    """What a research run produced: the answered points, the numbered source
    list their citations index into, and what could not be answered."""

    points: list[ResearchPoint]
    sources: list[Source]  # citation n -> sources[n - 1]
    gaps: list[str] = []
    # Provenance/audit: every source any agent looked at, cited or not. A
    # superset of ``sources`` once the writer has pruned to what it cited.
    consulted_sources: list[Source] = []


class Report(BaseModel):
    content: str
    sources: list[Source]
    failed_subquestions: list[str] = []
