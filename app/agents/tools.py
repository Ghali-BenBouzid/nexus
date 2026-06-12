from abc import ABC, abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.schemas import Source


class ToolResult(BaseModel):
    content: str


class RetrievalResult(ToolResult):
    sources: list[Source] = []


class SearchHit(BaseModel):
    title: str
    url: str
    content: str  # snippet returned by the search backend


class SearchBackend(Protocol):
    """A swappable web-retrieval backend (Tavily, Brave, ...). Isolates the
    concrete search provider from the tools that depend on it. It is an async
    context manager so the job can scope the client's lifetime with
    ``async with backend:`` (mirrors LLMProvider)."""

    async def __aenter__(self) -> "SearchBackend": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def search(self, query: str, max_results: int) -> list[SearchHit]: ...

    async def extract(self, url: str) -> str: ...


class ToolSpec(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]


class Tool(ToolSpec, Protocol):
    async def execute(self, **kwargs: Any) -> ToolResult: ...


class BaseToolSpec(ABC):
    """Shared spec plumbing: the JSON-schema parameters are derived from
    args_model, so each tool only declares its name, description, and args."""

    name: str
    description: str
    args_model: type[BaseModel]

    @property
    def parameters(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()


class BaseTool(BaseToolSpec):
    """Executable tool: validates incoming kwargs through args_model before
    running the tool's real work."""

    async def execute(self, **kwargs: Any) -> ToolResult:
        args = self.args_model(**kwargs)
        return await self._run(args)

    @abstractmethod
    async def _run(self, args: BaseModel) -> ToolResult: ...


class SubmitPlanArgs(BaseModel):
    sub_questions: list[str] = Field(description="The list of sub-questions")


class SubmitPlan(BaseToolSpec):
    name = "submit_plan"
    description = (
        "Submit the final research plan as a list of complementary "
        "sub-questions that together exhaustively cover the user's question."
    )
    args_model = SubmitPlanArgs


class SubmitFindingArgs(BaseModel):
    answer: str = Field(description="The answer to the sub-question")
    cited_source_ids: list[int] = Field(
        description="IDs of sources that back the answer; "
        "empty list if no relevant info was found"
    )
    found_info: bool = Field(description="False if no relevant info was found")


class SubmitFinding(BaseToolSpec):
    name = "submit_finding"
    description = "Use this tool to submit your findings with cited sources."
    args_model = SubmitFindingArgs


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query to run against the web")
    max_results: int = Field(default=5, description="How many results to return")


class WebSearch(BaseTool):
    name = "web_search"
    description = "Run a web search for a query and return up to max_results results."
    args_model = WebSearchArgs

    def __init__(self, backend: SearchBackend) -> None:
        self.backend = backend

    async def _run(self, args: WebSearchArgs) -> RetrievalResult:
        hits = await self.backend.search(args.query, args.max_results)
        sources = [Source(title=hit.title, url=hit.url) for hit in hits]
        content = (
            "\n\n".join(f"{hit.title}\n{hit.url}\n{hit.content}" for hit in hits)
            or "No results found."
        )
        return RetrievalResult(content=content, sources=sources)


class FetchPageArgs(BaseModel):
    url: str = Field(description="The URL of the page to fetch and read in full")


MAX_PAGE_CHARS = 6_000  # cap fetched page text so it can't blow the token budget


class FetchPage(BaseTool):
    name = "fetch_page"
    description = (
        "Fetch a web page by URL and return its cleaned full text, for when a "
        "search snippet is promising but insufficient."
    )
    args_model = FetchPageArgs

    def __init__(self, backend: SearchBackend) -> None:
        self.backend = backend

    async def _run(self, args: FetchPageArgs) -> RetrievalResult:
        text = await self.backend.extract(args.url)
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + "\n\n[...truncated]"
        return RetrievalResult(
            content=text,
            sources=[Source(title=args.url, url=args.url)],
        )
