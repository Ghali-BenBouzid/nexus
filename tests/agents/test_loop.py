import asyncio

import pytest
from pydantic import BaseModel

from app.agents.loop import Budget, Sources, StoppedError, run
from app.agents.provider import LLMResponse, Message, ToolCall
from app.agents.schemas import Source
from app.agents.tools import BaseTool, RetrievalResult, ToolResult


class _Args(BaseModel):
    query: str = ""


class _Search(BaseTool):
    name = "web_search"
    description = "search"
    args_model = _Args

    def __init__(self, hits: list[Source] | None = None, boom: bool = False) -> None:
        self.hits = hits or []
        self.boom = boom
        self.calls: list[str] = []

    async def _run(self, args: _Args) -> ToolResult:
        self.calls.append(args.query)
        if self.boom:
            raise RuntimeError("backend down")
        return RetrievalResult(
            content="<search_results>hits</search_results>", sources=self.hits
        )


class _Provider:
    """Replays scripted responses, so a test scripts a whole turn."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses

    async def generate(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        return self.responses.pop(0)


def _call(name: str, **args) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=name, name=name, args=args)])


def _go(
    provider,
    messages,
    *,
    executables=None,
    budget=None,
    sources=None,
    should_cancel=lambda: False,
):
    tools = executables or {}
    return asyncio.run(
        run(
            messages,
            provider=provider,
            specs=list(tools.values()),
            executables=tools,
            control={"answer"},
            sources=sources or Sources(),
            budget=budget or Budget(max_steps=5),
            should_cancel=should_cancel,
        )
    )


def test_the_loop_runs_tools_until_a_control_call() -> None:
    search = _Search(hits=[Source(title="A", url="https://a.example")])
    provider = _Provider(
        [
            _call("web_search", query="first"),
            _call("web_search", query="second"),
            _call("answer", text="done"),
        ]
    )
    messages: list[Message] = [Message(role="user", content="q")]

    call = _go(provider, messages, executables={"web_search": search})

    assert call is not None
    assert call.name == "answer" and call.args == {"text": "done"}
    assert search.calls == ["first", "second"]
    assert [m.role for m in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "tool",
        "assistant",
    ]


def test_retrieved_sources_are_numbered_once_across_the_turn() -> None:
    a = Source(title="A", url="https://a.example")
    b = Source(title="B", url="https://b.example")
    search = _Search(hits=[a, b])
    sources = Sources()
    provider = _Provider(
        [
            _call("web_search", query="one"),
            _call("web_search", query="two"),  # the same two sources again
            _call("answer", text="done"),
        ]
    )
    messages: list[Message] = [Message(role="user", content="q")]

    _go(provider, messages, executables={"web_search": search}, sources=sources)

    assert [s.url for s in sources.items] == ["https://a.example", "https://b.example"]
    legend = [m.content for m in messages if m.role == "tool"][0]
    assert "[1] A (https://a.example)" in legend
    assert "[2] B (https://b.example)" in legend


def test_a_failing_tool_is_reported_to_the_agent_not_raised() -> None:
    provider = _Provider([_call("web_search", query="x"), _call("answer", text="ok")])
    messages: list[Message] = [Message(role="user", content="q")]

    call = _go(provider, messages, executables={"web_search": _Search(boom=True)})

    assert call is not None and call.name == "answer"
    assert "backend down" in [m.content for m in messages if m.role == "tool"][0]


def test_an_unknown_tool_name_is_answered_not_fatal() -> None:
    provider = _Provider([_call("teleport", where="mars"), _call("answer", text="ok")])
    messages: list[Message] = [Message(role="user", content="q")]

    call = _go(provider, messages, executables={})

    assert call is not None and call.name == "answer"
    said = [m.content for m in messages if m.role == "tool"][0]
    assert "no tool called teleport" in said


def test_a_reply_with_no_tool_call_is_nudged() -> None:
    provider = _Provider(
        [LLMResponse(text="just chatting"), _call("answer", text="ok")]
    )
    messages: list[Message] = [Message(role="user", content="q")]

    call = _go(provider, messages, executables={})

    assert call is not None and call.name == "answer"
    assert messages[2].content == "Use one of your tools to continue."


def test_the_step_budget_ends_a_turn_that_will_not_stop() -> None:
    search = _Search()
    provider = _Provider([_call("web_search", query=str(i)) for i in range(10)])
    messages: list[Message] = [Message(role="user", content="q")]

    call = _go(
        provider,
        messages,
        executables={"web_search": search},
        budget=Budget(max_steps=3),
    )

    assert call is None  # the caller decides what an unfinished turn means
    assert len(search.calls) == 3


def test_a_stop_ends_the_loop_before_the_next_call() -> None:
    provider = _Provider([_call("answer", text="never")])
    messages: list[Message] = [Message(role="user", content="q")]

    with pytest.raises(StoppedError):
        _go(provider, messages, should_cancel=lambda: True)
