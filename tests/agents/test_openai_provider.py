import json

import httpx
import pytest

from app.agents.openai_provider import OpenAICompatibleProvider
from app.agents.provider import Message, ProviderCreditsError, ProviderError, ToolCall
from app.agents.rate_limit import RateLimiter
from app.agents.retry import RetryPolicy
from app.agents.tools import SubmitFinding

# A limiter fast enough to never pace in tests.
FAST = RateLimiter(rpm=10**9, tpm=10**9)

# No backoff sleeps in tests.
NO_BACKOFF = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0)


def _provider(handler, retry: RetryPolicy | None = None) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="http://test/v1",
        model="test-model",
        api_key="k",
        retry=retry,
        rate_limiter=FAST,
        transport=httpx.MockTransport(handler),
    )


def _tool_call_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tc1",
                                "type": "function",
                                "function": {
                                    "name": "submit_finding",
                                    "arguments": json.dumps(
                                        {
                                            "answer": "a",
                                            "cited_source_ids": [],
                                            "found_info": True,
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        },
    )


async def test_generate_retries_on_tool_use_failed():
    # Groq returns 400 tool_use_failed when the model emits a malformed tool call;
    # it is stochastic, so a retry re-rolls and usually succeeds.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "tool_use_failed",
                        "message": "Failed to call a function.",
                        "failed_generation": "<function=web_search [...]>",
                    }
                },
            )
        return _tool_call_response()

    async with _provider(handler, retry=NO_BACKOFF) as p:
        resp = await p.generate(
            [Message(role="user", content="q")],
            tools=[SubmitFinding()],
            tool_choice="auto",
        )
    assert calls["n"] == 2  # retried once, then succeeded
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].name == "submit_finding"


async def test_generate_reports_openrouter_cost():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "cost": 0.00042,
                },
            },
        )

    async with _provider(handler) as p:
        resp = await p.generate([Message(role="user", content="q")])
    assert resp.usage is not None
    assert resp.usage.cost_usd == 0.00042
    assert resp.usage.input_tokens == 10


async def test_out_of_credits_raises_a_distinct_error_without_retrying():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    async with _provider(handler, retry=NO_BACKOFF) as p:
        with pytest.raises(ProviderCreditsError):
            await p.generate([Message(role="user", content="q")])
    assert calls["n"] == 1


async def test_a_key_over_its_credit_limit_is_out_of_credits():
    # OpenRouter answers 403, not 402, once the key hits its limit: demo users got
    # "provider down" instead of the out-of-credits message.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = {"error": {"code": 403, "message": "Key limit exceeded (total limit)."}}
        return httpx.Response(403, json=body)

    async with _provider(handler, retry=NO_BACKOFF) as p:
        with pytest.raises(ProviderCreditsError):
            await p.generate([Message(role="user", content="q")])
    assert calls["n"] == 1


async def test_other_403s_stay_generic_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"error": {"code": 403, "message": "Your input was flagged"}}
        return httpx.Response(403, json=body)

    async with _provider(handler, retry=NO_BACKOFF) as p:
        with pytest.raises(ProviderError) as raised:
            await p.generate([Message(role="user", content="q")])
    assert not isinstance(raised.value, ProviderCreditsError)


async def test_generate_does_not_retry_generic_400():
    # A genuine bad request must fail fast — no retry storm.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            400, json={"error": {"code": "invalid_request_error", "message": "bad"}}
        )

    async with _provider(handler, retry=NO_BACKOFF) as p:
        with pytest.raises(ProviderError):
            await p.generate([Message(role="user", content="q")])
    assert calls["n"] == 1


def test_parse_captures_tool_call_extra_content():
    # Gemini 3 returns a thought_signature under extra_content that must round-trip.
    data = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "extra_content": {"google": {"thought_signature": "SIG"}},
                            "function": {"name": "web_search", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    resp = OpenAICompatibleProvider._parse(data)
    assert resp.tool_calls[0].extra == {"google": {"thought_signature": "SIG"}}


def test_to_messages_echoes_tool_call_extra_content():
    p = OpenAICompatibleProvider(base_url="http://x", model="m", api_key="k")
    out = p._to_messages(
        [
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="web_search",
                        args={"query": "x"},
                        extra={"google": {"thought_signature": "SIG"}},
                    )
                ],
            ),
        ]
    )
    assert out[0]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "SIG"}
    }


def test_to_messages_maps_roles_and_tool_calls():
    p = OpenAICompatibleProvider(base_url="http://x", model="m", api_key="k")
    out = p._to_messages(
        [
            Message(role="system", content="sys"),
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="c1", name="web_search", args={"query": "x"})],
            ),
            Message(
                role="tool", tool_call_id="c1", name="web_search", content="result"
            ),
        ]
    )
    assert out[0] == {"role": "system", "content": "sys"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2]["tool_calls"][0]["function"] == {
        "name": "web_search",
        "arguments": json.dumps({"query": "x"}),
    }
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "result"}


def test_to_tools_and_tool_choice():
    p = OpenAICompatibleProvider(base_url="http://x", model="m", api_key="k")
    tools = p._to_tools([SubmitFinding()])
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "submit_finding"
    assert "parameters" in tools[0]["function"]
    assert p._to_tool_choice("auto") == "auto"
    assert p._to_tool_choice("required") == "required"
    assert p._to_tool_choice("submit_finding") == {
        "type": "function",
        "function": {"name": "submit_finding"},
    }


async def test_generate_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello"}}]}
        )

    async with _provider(handler) as p:
        resp = await p.generate([Message(role="user", content="hi")])
    assert resp.text == "hello"
    assert resp.tool_calls is None


async def test_generate_returns_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "type": "function",
                                    "function": {
                                        "name": "submit_finding",
                                        "arguments": json.dumps(
                                            {
                                                "answer": "a",
                                                "cited_source_ids": [],
                                                "found_info": True,
                                            }
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async with _provider(handler) as p:
        resp = await p.generate(
            [Message(role="user", content="q")],
            tools=[SubmitFinding()],
            tool_choice="submit_finding",
        )
    assert resp.tool_calls is not None
    assert resp.tool_calls[0].name == "submit_finding"
    assert resp.tool_calls[0].args["answer"] == "a"
