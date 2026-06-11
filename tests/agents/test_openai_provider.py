import json

import httpx

from app.agents.openai_provider import OpenAICompatibleProvider
from app.agents.provider import Message, ToolCall
from app.agents.rate_limit import AsyncTokenBucket
from app.agents.tools import SubmitFinding

# A limiter fast enough to never pace in tests.
FAST = AsyncTokenBucket(rate_per_min=600000)


def _provider(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="http://test/v1",
        model="test-model",
        api_key="k",
        rate_limiter=FAST,
        transport=httpx.MockTransport(handler),
    )


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
