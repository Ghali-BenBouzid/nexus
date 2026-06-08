import uuid
from typing import Any, Literal, Protocol

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.agents.tools import ToolSpec


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None  # on an assistant tool-call message
    tool_call_id: str | None = None  # on a tool-result message
    name: str | None = None  # tool name on a tool result (Gemini matches by it)


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLMProvider(Protocol):
    async def __aenter__(self) -> "LLMProvider": ...

    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
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
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        self.calls.append((messages, tools, tool_choice))
        return self.responses.pop(0)


class GeminiProvider:
    """Adapter over the google-genai SDK. Translates neutral types <-> SDK and
    does exactly one model round-trip per ``generate``. Use as an async context
    manager so the SDK client is opened and closed with the job."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self._client: genai.Client | None = None

    async def __aenter__(self) -> "GeminiProvider":
        self._client = genai.Client(api_key=self.api_key)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.aio.aclose()
            self._client = None

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        if self._client is None:
            raise RuntimeError("GeminiProvider must be used within 'async with'")

        system_instruction, contents = self._to_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            tools=self._to_tools(tools),
            tool_config=self._to_tool_config(tool_choice, tools),
        )
        response = await self._client.aio.models.generate_content(
            model=self.model, contents=contents, config=config
        )

        calls = response.function_calls
        if calls:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=call.id or uuid.uuid4().hex,
                        name=call.name or "",
                        args=dict(call.args or {}),
                    )
                    for call in calls
                ]
            )
        return LLMResponse(text=response.text)

    @staticmethod
    def _to_contents(
        messages: list[Message],
    ) -> tuple[str, list[types.Content]]:
        """Split out system messages (Gemini takes them separately) and map the
        rest to SDK ``Content`` (roles: user/model; tool results as function
        responses under a user-role turn)."""
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            if message.role == "system":
                if message.content:
                    system_parts.append(message.content)
            elif message.role == "tool":
                part = types.Part.from_function_response(
                    name=message.name or "",
                    response={"result": message.content},
                )
                contents.append(types.Content(role="user", parts=[part]))
            elif message.role == "assistant":
                parts: list[types.Part] = []
                if message.content:
                    parts.append(types.Part.from_text(text=message.content))
                for call in message.tool_calls or []:
                    parts.append(
                        types.Part.from_function_call(name=call.name, args=call.args)
                    )
                contents.append(types.Content(role="model", parts=parts))
            else:  # user
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=message.content or "")],
                    )
                )

        return "\n\n".join(system_parts), contents

    @staticmethod
    def _to_tools(tools: list[ToolSpec] | None) -> list[types.Tool] | None:
        if not tools:
            return None
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _to_tool_config(
        tool_choice: str, tools: list[ToolSpec] | None
    ) -> types.ToolConfig | None:
        # "auto" (or no tools) -> SDK default (AUTO), so send nothing.
        if not tools or tool_choice == "auto":
            return None
        mode = types.FunctionCallingConfigMode.ANY  # force a function call
        allowed = None if tool_choice == "required" else [tool_choice]
        return types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=mode, allowed_function_names=allowed
            )
        )
