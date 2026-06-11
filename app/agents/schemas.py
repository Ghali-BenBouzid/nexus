from typing import Any

from pydantic import BaseModel


class Source(BaseModel):
    title: str
    url: str


class Finding(BaseModel):
    sub_question: str
    answer: str
    cited_sources: list[Source] = []  # sources submit_finding referenced -> drive [n]
    consulted_sources: list[Source] = []  # everything fetched -> provenance/audit
    found_info: bool = True


class AgentEvent(BaseModel):
    """A minimal progress event emitted while agents work. Stable ``type`` +
    human ``message`` for a basic feed now; open ``data`` for later."""

    type: str
    message: str
    data: dict[str, Any] | None = None


class ResearchPoint(BaseModel):
    sub_question: str
    answer: str
    source_ids: list[int]  # 1-based citation numbers into ResearchResult.sources


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
