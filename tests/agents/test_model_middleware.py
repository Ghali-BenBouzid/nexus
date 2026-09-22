"""The middleware that replaced the hand-rolled provider. Each test pins one
behaviour the old provider had, because losing any of them quietly is how a demo
account gets billed wrong or a stopped run keeps spending.
"""

import logging
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.agents import model as agent_model
from app.agents.provider import ProviderCreditsError, ProviderError
from app.agents.rate_limit import RateLimiter
from app.agents.schemas import AgentEvent


class _Request:
    """The slice of ModelRequest the middleware reads."""

    def __init__(self, messages=None, tools=None) -> None:
        self.messages = messages or [HumanMessage("hello")]
        self.tools = tools or []


def _reply(*, tokens=(10, 5), cost=0.00021, model="a/model") -> AIMessage:
    message = AIMessage("hi")
    message.usage_metadata = {
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "total_tokens": sum(tokens),
    }
    message.response_metadata = {
        "token_usage": {
            "prompt_tokens": tokens[0],
            "completion_tokens": tokens[1],
            "total_tokens": sum(tokens),
            "cost": cost,
        },
        "model_name": model,
    }
    return message


def _result(message: AIMessage) -> LLMResult:
    """What a callback is handed after a call."""
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def _handler(result):
    async def handler(request):
        if isinstance(result, Exception):
            raise result
        return result

    return handler


def _status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


# --- pacing -----------------------------------------------------------------


async def test_every_call_is_paced_including_one_no_agent_made() -> None:
    # Pacing lives in the model, not middleware: the planner and the writer call
    # the model directly, and a fan-out that paces only its researchers still
    # bursts past a free tier.
    acquired: list[int] = []

    class _Limiter(RateLimiter):
        async def acquire(self, tokens: int) -> None:
            acquired.append(tokens)

    model = agent_model.PacedChatOpenAI(
        model="m", base_url="http://x", api_key="k", pacing=_Limiter(rpm=60, tpm=1000)
    )

    with pytest.raises(Exception):  # noqa: B017 -- no server; pacing runs first
        await model._agenerate([HumanMessage("hello")])

    assert acquired and acquired[0] > 0  # an estimate, paid before the call


# --- billing ----------------------------------------------------------------


async def test_a_call_is_billed_with_its_tokens_and_cost() -> None:
    # A callback, not middleware: middleware only sees an agent's calls, and the
    # planner and writer call the model directly. Billing cannot have holes.
    billed: list[dict] = []
    usage = agent_model.Usage(record=lambda seen: _collect(billed, seen))

    await usage.on_llm_end(_result(_reply(tokens=(120, 40), cost=0.00042)), run_id=1)

    assert billed == [
        {
            "input_tokens": 120,
            "output_tokens": 40,
            "total_tokens": 160,
            "cost_usd": 0.00042,
            "model": "a/model",
        }
    ]


async def test_a_reply_without_usage_bills_nothing_rather_than_zero() -> None:
    billed: list[dict] = []
    usage = agent_model.Usage(record=lambda seen: _collect(billed, seen))

    await usage.on_llm_end(_result(AIMessage("hi")), run_id=1)

    assert billed == [
        {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
            "model": None,
        }
    ]


async def _collect(into: list, usage: dict) -> None:
    into.append(usage)


# --- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body"),
    [(402, "no credits"), (403, "Key limit exceeded (total limit)")],
)
async def test_a_refusal_for_money_says_the_credits_ran_out(status, body) -> None:
    middleware = agent_model.Errors()

    with pytest.raises(ProviderCreditsError, match="credits"):
        await middleware.awrap_model_call(
            _Request(), _handler(_status_error(status, body))
        )


@pytest.mark.parametrize(
    ("status", "body"),
    [(403, "flagged by moderation"), (500, "boom"), (429, "slow down")],
)
async def test_any_other_failure_is_a_generic_provider_error(status, body) -> None:
    # Never the SDK's own error: it can carry the request, and the key with it.
    middleware = agent_model.Errors()

    with pytest.raises(ProviderError) as caught:
        await middleware.awrap_model_call(
            _Request(), _handler(_status_error(status, body))
        )
    assert not isinstance(caught.value, ProviderCreditsError)


async def test_a_stop_is_not_dressed_up_as_a_provider_error() -> None:
    middleware = agent_model.Errors()

    with pytest.raises(agent_model.StoppedError):
        await middleware.awrap_model_call(
            _Request(), _handler(agent_model.StoppedError("stopped"))
        )


# --- stop and deadline ------------------------------------------------------


async def test_a_stopped_run_does_not_start_another_call() -> None:
    called = False

    async def handler(request):
        nonlocal called
        called = True
        return _reply()

    middleware = agent_model.Guard(should_cancel=lambda: True)

    with pytest.raises(agent_model.StoppedError):
        await middleware.awrap_model_call(_Request(), handler)
    assert not called


async def test_a_turn_out_of_time_does_not_start_another_call() -> None:
    middleware = agent_model.Guard(deadline=lambda: True)

    with pytest.raises(TimeoutError):
        await middleware.awrap_model_call(_Request(), _handler(_reply()))


# --- retry predicate --------------------------------------------------------


def test_out_of_credits_is_never_retried() -> None:
    assert not agent_model._retryable(ProviderCreditsError(agent_model.OUT_OF_CREDITS))
    assert not agent_model._retryable(agent_model.StoppedError("stopped"))


def test_a_transient_failure_and_a_mangled_tool_call_are_retried() -> None:
    mangled = '{"error": {"code": "tool_use_failed"}}'
    bad_request = '{"error": {"code": "bad_request"}}'

    assert agent_model._retryable(_status_error(503, "unavailable"))
    assert agent_model._retryable(_status_error(400, mangled))
    assert not agent_model._retryable(_status_error(400, bad_request))


# --- progress ---------------------------------------------------------------


async def test_the_feed_shows_thinking_and_tool_calls_tagged_by_agent() -> None:
    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    middleware = agent_model.Progress(emit, agent="researcher", index=2)

    await middleware.awrap_model_call(_Request(), _handler(_reply()))

    assert events[0].type == "thinking"
    assert events[0].data == {"agent": "researcher", "index": 2}


async def test_a_failing_tool_is_logged_with_its_cause_and_still_raises(caplog) -> None:
    """Every tool of every agent passes through here, so it is the one place
    that can say why one failed. The event the user sees carries a summary; the
    cause carries the stack and sometimes a host, so it goes only to the log."""
    events: list[AgentEvent] = []

    async def emit(event: AgentEvent) -> None:
        events.append(event)

    async def explode(_request):
        raise RuntimeError("Name or service not known")

    middleware = agent_model.Progress(emit, agent="supervisor")
    request = SimpleNamespace(tool_call={"name": "research", "args": {"q": "x"}})

    with caplog.at_level(logging.WARNING, logger="app.agents.model"):
        with pytest.raises(RuntimeError):
            await middleware.awrap_tool_call(request, explode)

    assert "tool research failed for supervisor" in caplog.text
    # The stack is what makes a deployment diagnosable at all.
    assert "Name or service not known" in caplog.text
    assert [event.type for event in events] == ["tool_call", "tool_error"]
