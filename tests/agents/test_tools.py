import pytest
from pydantic import BaseModel, Field, ValidationError

from app.agents.tools import BaseTool, SubmitFinding, SubmitPlan, ToolResult


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


def test_control_schemas_expose_parameters() -> None:
    plan = SubmitPlan()
    assert plan.name == "submit_plan"
    assert plan.parameters["required"] == ["sub_questions"]

    finding = SubmitFinding()
    assert finding.name == "submit_finding"
    assert set(finding.parameters["properties"]) == {
        "answer",
        "cited_source_ids",
        "found_info",
    }
