from app.agents.provider import FakeLLMProvider, LLMResponse, Message, ToolCall


async def test_fake_llm_provider() -> None:
    r1 = LLMResponse(text="first")
    r2 = LLMResponse(
        tool_calls=[ToolCall(id="c1", name="web_search", args={"query": "x"})]
    )
    r3 = LLMResponse(text="third")

    fake_provider = FakeLLMProvider(responses=[r1, r2, r3])

    msgs = [Message(role="user")]

    assert await fake_provider.generate(messages=msgs) == r1
    assert await fake_provider.generate(messages=msgs) == r2

    await fake_provider.generate(messages=msgs, tool_choice="submit_finding")
    assert fake_provider.calls == [
        (msgs, None, "auto"),
        (msgs, None, "auto"),
        (msgs, None, "submit_finding"),
    ]

    async with fake_provider as p:
        assert p is fake_provider
