import json
from typing import Any

import httpx

from app.agents.provider import LLMResponse, Message, ProviderError, ToolCall
from app.agents.rate_limit import RateLimiter, llm_rate_limiter
from app.agents.retry import RetryPolicy, is_transient, retry_async
from app.agents.tools import ToolSpec

# A rough chars-per-token ratio for English + JSON tool schemas. Token-bucket
# pacing only needs an estimate; the per-model TPM is set with a safety margin.
_CHARS_PER_TOKEN = 4
# Reserve room for the model's reply, which also counts against TPM.
_OUTPUT_TOKEN_RESERVATION = 1024


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
        rate_limiter: RateLimiter | None = None,
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

        estimated_tokens = _estimate_tokens(payload)

        async def _call() -> dict[str, Any]:
            # Pace every attempt (incl. retries) under both the request and token
            # budgets; token cost is what keeps a fan-out under the free-tier TPM.
            await self._limiter.acquire(estimated_tokens)
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()

        try:
            data = await retry_async(_call, policy=self.retry, transient=_retryable)
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
                        "tool_calls": [_tool_call_payload(c) for c in m.tool_calls],
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
                        extra=tc.get("extra_content"),
                    )
                    for tc in tool_calls
                ]
            )
        return LLMResponse(text=message.get("content"))


def _tool_call_payload(call: ToolCall) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": call.id,
        "type": "function",
        "function": {"name": call.name, "arguments": json.dumps(call.args)},
    }
    if call.extra is not None:
        # Echo provider passthrough unchanged (Gemini 3's thought_signature lives
        # here and must be replayed on later turns or the request 400s).
        payload["extra_content"] = call.extra
    return payload


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Estimate a request's token cost for TPM pacing: the serialized messages and
    tool schemas (the input billed against TPM) plus a reservation for the reply.
    Approximate by design — paired with a per-model TPM safety margin."""
    text = json.dumps(payload.get("messages", [])) + json.dumps(
        payload.get("tools", [])
    )
    return len(text) // _CHARS_PER_TOKEN + _OUTPUT_TOKEN_RESERVATION


def _tool_use_failed(exc: Exception) -> bool:
    """True for Groq's ``400 tool_use_failed`` — the model emitted a tool call the
    server could not parse (e.g. Llama's native ``<function=...>`` syntax instead
    of JSON). It is stochastic, so a fresh generation usually parses; we treat it
    as transient and let the retry re-roll. Scoped to this one error code so real
    bad requests (bad key, malformed payload) still fail fast."""
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) != 400:
        return False
    try:
        body = response.json()
    except Exception:
        return False
    return isinstance(body, dict) and body.get("error", {}).get("code") == (
        "tool_use_failed"
    )


def _retryable(exc: Exception) -> bool:
    return is_transient(exc) or _tool_use_failed(exc)


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
