from abc import ABC, abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.schemas import Source


class ToolResult(BaseModel):
    content: str


class RetrievalResult(ToolResult):
    sources: list[Source] = []


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

    async def _run(self, args: WebSearchArgs) -> RetrievalResult:
        raise NotImplementedError  # backend call
