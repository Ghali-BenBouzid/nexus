import pytest
from pydantic import BaseModel, Field, ValidationError

from app.agents.tools import (
    MAX_PAGE_CHARS,
    BaseTool,
    FetchPage,
    SearchHit,
    SubmitFinding,
    SubmitPlan,
    ToolResult,
    WebSearch,
)


class FakeSearchBackend:
    """Canned SearchBackend so tool tests never hit the network."""

    def __init__(self, hits: list[SearchHit] | None = None, page: str = "") -> None:
        self.hits = hits or []
        self.page = page

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return self.hits[:max_results]

    async def extract(self, url: str) -> str:
        return self.page


class DummyArgs(BaseModel):
    arg1: str = Field(description="first arg")
    arg2: int = Field(description="second arg")


class DummyTool(BaseTool):
    name = "dummy_tool"
    description = "Use this tool for tests"
    args_model = DummyArgs

    async def _run(self, args: DummyArgs) -> ToolResult:
        return ToolResult(content=f"{args.arg1}:{args.arg2}")


async def test_execute_validates_and_runs() -> None:
    tool = DummyTool()
    result = await tool.execute(arg1="hello", arg2=5)
    assert result.content == "hello:5"


async def test_execute_rejects_bad_kwargs() -> None:
    tool = DummyTool()
    with pytest.raises(ValidationError):
        await tool.execute(arg1="hello", arg2="not-an-int")  # arg2 not coercible to int


def test_basetool_requires_run() -> None:
    class Incomplete(BaseTool):  # no _run implementation
        name = "incomplete"
        description = "x"
        args_model = DummyArgs

    with pytest.raises(TypeError):  # abstractmethod -> can't instantiate
        Incomplete()


async def test_web_search_maps_hits_to_sources() -> None:
    hits = [
        SearchHit(title="A", url="http://a", content="snippet a"),
        SearchHit(title="B", url="http://b", content="snippet b"),
    ]
    tool = WebSearch(backend=FakeSearchBackend(hits=hits))

    result = await tool.execute(query="x", max_results=5)

    assert [s.url for s in result.sources] == ["http://a", "http://b"]
    assert "snippet a" in result.content and "snippet b" in result.content


async def test_web_search_handles_no_results() -> None:
    tool = WebSearch(backend=FakeSearchBackend(hits=[]))
    result = await tool.execute(query="x", max_results=5)
    assert result.sources == []
    assert result.content == "No results found."


async def test_fetch_page_returns_text_and_source() -> None:
    tool = FetchPage(backend=FakeSearchBackend(page="full page text"))
    result = await tool.execute(url="http://a")
    assert result.content == "full page text"
    assert [s.url for s in result.sources] == ["http://a"]


async def test_fetch_page_truncates_long_text() -> None:
    tool = FetchPage(backend=FakeSearchBackend(page="x" * (MAX_PAGE_CHARS + 500)))
    result = await tool.execute(url="http://a")
    assert len(result.content) < MAX_PAGE_CHARS + 100
    assert result.content.endswith("[...truncated]")


def test_control_schemas_expose_parameters() -> None:
    plan = SubmitPlan()
    assert plan.name == "submit_plan"
    assert plan.parameters["required"] == ["sub_questions"]

    finding = SubmitFinding()
    assert finding.name == "submit_finding"
    assert set(finding.parameters["properties"]) == {"claims", "found_info"}
