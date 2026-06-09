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
