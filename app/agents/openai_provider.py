import json
from typing import Any

import httpx

from app.agents.provider import LLMResponse, Message, ProviderError, ToolCall
from app.agents.rate_limit import AsyncTokenBucket, llm_rate_limiter
from app.agents.retry import RetryPolicy, retry_async
from app.agents.tools import ToolSpec


class OpenAICompatibleProvider:
    """An LLMProvider over any OpenAI-compatible /chat/completions endpoint
    (Groq, Cerebras, SambaNova, ...). Translates our neutral types <-> the OpenAI
    shape and does one round-trip per generate, paced by the shared rate limiter
    and retried on transient errors. Use as an async context manager."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        retry: RetryPolicy | None = None,
        rate_limiter: AsyncTokenBucket | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.retry = retry or RetryPolicy()
        self._limiter = rate_limiter or llm_rate_limiter
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "OpenAICompatibleProvider":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        client = self._client
        if client is None:
            raise RuntimeError(
                "OpenAICompatibleProvider must be used within 'async with'"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_messages(messages),
        }
        if tools:
            payload["tools"] = self._to_tools(tools)
            payload["tool_choice"] = self._to_tool_choice(tool_choice)

        async def _call() -> dict[str, Any]:
            await self._limiter.acquire()  # pace every attempt, incl. retries
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()

        try:
            data = await retry_async(_call, policy=self.retry)
        except Exception as exc:  # never let a raw/key-bearing error escape
            raise ProviderError("LLM request failed") from exc
        return self._parse(data)

    @staticmethod
    def _to_messages(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                out.append(
                    {
                        "role": "assistant",
                        "content": m.content or "",
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {
                                    "name": c.name,
                                    "arguments": json.dumps(c.args),
                                },
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            elif m.role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id or "",
                        "content": m.content or "",
                    }
                )
            else:
                out.append({"role": m.role, "content": m.content or ""})
        return out

    @staticmethod
    def _to_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_tool_choice(tool_choice: str) -> Any:
        if tool_choice in ("auto", "required"):
            return tool_choice
        return {"type": "function", "function": {"name": tool_choice}}

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls")
        if tool_calls:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=tc.get("id") or "",
                        name=tc["function"]["name"],
                        args=_loads(tc["function"].get("arguments")),
                    )
                    for tc in tool_calls
                ]
            )
        return LLMResponse(text=message.get("content"))


def _loads(raw: str | None) -> dict[str, Any]:
    # A model can emit malformed argument JSON; return {} so downstream pydantic
    # validation fails cleanly and is fed back, rather than crashing the parse.
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
