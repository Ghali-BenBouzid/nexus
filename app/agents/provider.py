from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.agents.tools import Tool


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # on a tool-result message


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLMProvider(Protocol):
    async def __aenter__(self) -> "LLMProvider": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def generate(
        self,
        messages: list[Message],
        tools: list["Tool"] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse: ...


class FakeLLMProvider:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.calls: list[tuple] = []  # call arguments

    async def __aenter__(self) -> "FakeLLMProvider":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def generate(
        self,
        messages: list[Message],
        tools: list["Tool"] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        self.calls.append((messages, tools, tool_choice))
        return self.responses.pop(0)
