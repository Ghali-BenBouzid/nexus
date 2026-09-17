"""What one eval run of a golden records, stage by stage, and how it scored.

The collector fills a RunTrace from the current pipeline and the metrics read only
the trace. When the engine moves to LangGraph, a new collector fills the same
shape and every metric keeps working, so scores stay comparable across the
rewrite.
"""

from pydantic import BaseModel, Field


class SearchHitRecord(BaseModel):
    title: str
    url: str
    snippet: str


class SearchCall(BaseModel):
    query: str
    hits: list[SearchHitRecord] = Field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0


class FetchCall(BaseModel):
    url: str
    text: str = ""
    error: str | None = None
    seconds: float = 0.0


class ClaimRecord(BaseModel):
    text: str
    source_urls: list[str] = Field(default_factory=list)


class ResearcherTrace(BaseModel):
    sub_question: str
    searches: list[SearchCall] = Field(default_factory=list)
    fetches: list[FetchCall] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)
    found_info: bool = False
    # Agent events that explain a failure: forced finish, malformed submit, tool error.
    events: list[str] = Field(default_factory=list)
    error: str | None = None  # the researcher crashed or timed out
    seconds: float = 0.0

    @property
    def finding(self) -> str:
        return " ".join(claim.text for claim in self.claims)

    @property
    def evidence(self) -> list[str]:
        """Everything the researcher actually read: search snippets and pages."""
        snippets = [
            f"{hit.title} ({hit.url}): {hit.snippet}"
            for search in self.searches
            for hit in search.hits
        ]
        pages = [f"{page.url}: {page.text}" for page in self.fetches if page.text]
        return snippets + pages

    @property
    def succeeded(self) -> bool:
        """Found information and backed at least one claim with a source."""
        return self.found_info and any(claim.source_urls for claim in self.claims)


class SourceRecord(BaseModel):
    title: str
    url: str


class StageUsage(BaseModel):
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Time spent waiting on the model, summed over calls (concurrent researchers
    # overlap, so the research stage can exceed its wall-clock time).
    seconds: float = 0.0
    slowest_call_seconds: float = 0.0


class RunTrace(BaseModel):
    golden_id: str
    input: str
    run_date: str  # ISO date of the run: what "current" meant for this run
    model: str
    route: str | None = None  # answer | research | compose
    reply: str | None = None  # the direct answer, on the answer route
    research_query: str | None = None  # the supervisor's self-contained rewrite
    supervisor_searches: list[SearchCall] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    researchers: list[ResearcherTrace] = Field(default_factory=list)
    # The consolidated claims the writer received, with their citation numbers.
    consolidated: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    report: str | None = None
    sources: list[SourceRecord] = Field(default_factory=list)
    error: str | None = None
    seconds: float = 0.0
    usage: dict[str, StageUsage] = Field(default_factory=dict)

    @property
    def response(self) -> str:
        """What the user finally sees: the report, or the direct answer."""
        return self.report or self.reply or ""

    @property
    def cost_usd(self) -> float:
        return sum(stage.cost_usd for stage in self.usage.values())


class MetricResult(BaseModel):
    name: str
    stage: str  # routing | plan | research | report | response | system
    score: float | None = None  # 0 to 1, higher is better; None when not scored
    passed: bool | None = None
    value: float | None = None  # a raw measurement (seconds, dollars, counts)
    reason: str = ""


class RunScore(BaseModel):
    golden_id: str
    category: str
    metrics: list[MetricResult]
