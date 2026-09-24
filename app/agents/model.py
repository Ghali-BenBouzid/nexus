"""The chat model the agents run on, and the middleware around every call.

The agents are LangChain agents now, so the model is a ``ChatOpenAI`` pointed at
whichever OpenAI-compatible provider the settings name. Everything the old
hand-rolled provider did around a call survives here as middleware, because each
piece is load-bearing:

- **Pacing** under the provider's requests and tokens per minute, which is what
  keeps a six-researcher fan-out off a 429 on a free tier.
- **Billing**: every call's tokens and cost, as the provider reports them
  (OpenRouter puts ``cost`` in ``usage``), written to the ledger that demo
  budgets are spent from.
- **Errors**: a refusal for money becomes ``ProviderCreditsError`` so the user is
  told the credits ran out; anything else becomes ``ProviderError``. A raw SDK
  error must never reach a user, as it can carry the key.
- **Stop and deadline**: checked before each call, so a stopped run stops
  spending instead of finishing its turn.
- **Progress**: a ``thinking`` event before a call and a tool event around each
  tool, which is what the live feed in the chat is made of.

Retries stay LangChain's (``ModelRetryMiddleware``), with our own predicate: out
of credits is final, since backing off cannot bring the money back.
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    ToolCallRequest,
    hook_config,
)
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI
from langgraph.types import Command

from app.agents.provider import ProviderCreditsError, ProviderError
from app.agents.retry import is_transient
from app.agents.schemas import AgentEvent
from app.observability import STAGE

logger = logging.getLogger(__name__)

Emit = Callable[[AgentEvent], Awaitable[None]]
ShouldCancel = Callable[[], bool]

OUT_OF_CREDITS = "The model credits behind this demo have run out."

# Where a streamed chunk carries the model's thinking, on the message and in the
# provider's delta. OpenRouter's name for it; not part of the OpenAI schema.
REASONING = "reasoning"
# Which agent produced a streamed chunk, stamped on it as it is decoded. The
# graph's own metadata cannot say: a sub-agent is its own ``create_agent`` graph
# and its model node is called "model" too, so a researcher's chunks look
# exactly like the supervisor's. The stage is set around the call itself and a
# chunk is decoded inside that call, so it is the one label that travels.
STAGE_KEY = "nexus_stage"

# Rough token accounting for pacing only: the real count comes back with the
# response and is billed exactly. Paired with a TPM safety margin.
_CHARS_PER_TOKEN = 4
_OUTPUT_TOKEN_RESERVATION = 1_000


class StoppedError(Exception):
    """The user stopped the run while an agent was working."""


class PacedChatOpenAI(ChatOpenAI):
    """A chat model that holds itself under the provider's per-minute ceilings.

    Pacing lives in the model, not in middleware, for the same reason billing
    does: middleware only wraps an agent's calls, and the planner and the writer
    call the model directly. A fan-out that paces only its researchers still
    bursts past a free tier.

    ``pacing`` is ours and token-aware; LangChain's own ``rate_limiter`` field
    counts requests only, which is the wrong ceiling on a free tier where tokens
    per minute bind first.
    """

    pacing: Any = None  # a RateLimiter, or None to run unpaced

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.pacing is not None:
            await self.pacing.acquire(_estimate_call(messages, kwargs.get("tools")))
        return await super()._agenerate(messages, stop, run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if self.pacing is not None:
            await self.pacing.acquire(_estimate_call(messages, kwargs.get("tools")))
        async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
            yield chunk

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ):
        """Keep the model's reasoning and what the call cost, both of which the
        base class drops on a streamed response.

        A reasoning model spends most of a turn thinking before it writes a
        word: the first ``reasoning`` delta arrives seconds before the first
        ``content`` one. That thinking is what the live feed shows while the
        answer is still being formed, so a stream without it is a stream that
        starts at the end.

        Cost rides the stream's final usage block, but only its token counts
        are carried through; ``token_usage`` is where a non-streamed call keeps
        the raw block, and it is where billing reads the dollar figure from. An
        account whose budget stops going down is worse than a slow one.

        ``langchain-openai`` reads ``delta.content`` and the counts only, and
        says as much in its own docstring: provider extras like these want a
        provider-specific subclass. This is that subclass.
        """
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation is None:
            return None
        generation.message.additional_kwargs[STAGE_KEY] = STAGE.get()
        thought = _reasoning_of(chunk)
        if thought:
            generation.message.additional_kwargs[REASONING] = thought
        usage = chunk.get("usage")
        if usage:
            generation.message.response_metadata["token_usage"] = usage
        return generation


def build_model(
    *, model: str, base_url: str, api_key: str, **kwargs: Any
) -> PacedChatOpenAI:
    """The chat model for one provider. Retrying is middleware, with our own
    predicate, so the client itself does not retry."""
    return PacedChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_retries=0,  # ModelRetryMiddleware owns retrying, with our predicate
        # A streamed call reports its tokens and cost only when asked to, and
        # langchain-openai asks by default only against OpenAI's own base URL.
        # Every provider here is a different one, so without this a streamed
        # turn is billed nothing and a demo budget never runs down.
        stream_usage=True,
        **kwargs,
    )


class Usage(AsyncCallbackHandler):
    """Every model call's tokens and cost, wherever it was made.

    A callback rather than middleware on purpose: middleware only wraps an
    agent's calls, and the planner and the writer call the model directly. What
    an account is billed cannot depend on which agent happened to spend it.
    """

    def __init__(self, record: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self.record = record

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        for generation in response.generations:
            for item in generation:
                message = getattr(item, "message", None)
                if isinstance(message, AIMessage):
                    await self.record(_usage_of(message) or {})


class Guard(AgentMiddleware):
    """Refuses to start another call once the user has stopped the run or the
    turn is out of time. Checked before the call, because the point is not to
    spend on a run nobody is waiting for."""

    def __init__(
        self,
        *,
        should_cancel: ShouldCancel = lambda: False,
        deadline: Callable[[], bool] = lambda: False,
    ) -> None:
        super().__init__()
        self.should_cancel = should_cancel
        self.out_of_time = deadline

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        if self.should_cancel():
            raise StoppedError("the run was stopped")
        if self.out_of_time():
            raise TimeoutError("the turn ran out of time")
        return await handler(request)


class Deadline(AgentMiddleware):
    """Ends an agent's loop once its time is up, rather than failing it: a
    researcher out of time still has findings worth submitting, and the caller
    asks it once more with the schema forced. Pair with a caller that knows what
    to do with an unfinished loop."""

    def __init__(self, deadline: float | None) -> None:
        super().__init__()
        self.deadline = deadline

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime) -> dict[str, Any] | None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return {
                "jump_to": "end",
                "messages": [AIMessage(content="Out of time for this step.")],
            }
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self.before_model(state, runtime)


class LastStep(AgentMiddleware):
    """Tells an agent that the model call it is about to make is its last, so
    it finishes on purpose instead of being cut off mid-thought: a researcher
    submits what it read, a supervisor answers with what it has. Pair it with
    the ModelCallLimitMiddleware whose limit it mirrors.

    The note rides on that one request only; nothing is added to the agent's
    state, so the conversation it leaves behind is the one it actually had.
    """

    def __init__(self, limit: int, note: str) -> None:
        super().__init__()
        self.limit = limit
        self.note = note

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        if _calls_this_run(request.messages) == self.limit - 1:
            request = request.override(
                messages=[*request.messages, HumanMessage(self.note)]
            )
        return await handler(request)


def _calls_this_run(messages: list) -> int:
    """Model calls made since the user's message: every AI turn after the last
    human one. Earlier turns of a conversation come before it, so they are not
    counted."""
    count = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        count += isinstance(message, AIMessage)
    return count


class Errors(AgentMiddleware):
    """Turns a provider failure into one of our two errors, so a user sees
    "credits ran out" or "provider unavailable" and never an SDK traceback that
    may carry the key."""

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        try:
            return await handler(request)
        except (StoppedError, TimeoutError, ProviderError):
            raise
        except Exception as exc:
            if out_of_credits(exc):
                raise ProviderCreditsError(OUT_OF_CREDITS) from exc
            logger.warning("model call failed", exc_info=exc)
            raise ProviderError("LLM request failed") from exc


class Progress(AgentMiddleware):
    """The live feed: a ``thinking`` event before each model call, and a tool
    event around each tool, tagged with which agent is working so the chat can
    nest a sub-agent's steps under the one that called it."""

    def __init__(self, emit: Emit, *, agent: str, **data: Any) -> None:
        super().__init__()
        self.emit = emit
        self.agent = agent
        self.data = data

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        await self.emit(
            AgentEvent(
                type="thinking",
                message=f"{self.agent.capitalize()} is thinking",
                data={"agent": self.agent, **self.data},
            )
        )
        return await handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler
    ) -> ToolMessage | Command:
        name = request.tool_call["name"]
        await self.emit(
            AgentEvent(
                type="tool_call",
                message=f"{name}({request.tool_call['args']})",
                # The arguments are what the feed shows (the query, the page),
                # and the call's id is what ties a research team's own events
                # back to the step that sent it.
                data={
                    "agent": self.agent,
                    "tool": name,
                    "args": request.tool_call["args"],
                    "call": request.tool_call.get("id"),
                    **self.data,
                },
            )
        )
        try:
            return await handler(request)
        except Exception as exc:
            # Every tool of every agent passes through here, so this is the one
            # place that sees them all: research, the document and report
            # readers, the runs the supervisor starts. The event carries a
            # summary for the user; the cause carries the stack, a status code
            # and sometimes a host, so it goes to the log and nowhere else.
            # (web_search and fetch_page never reach this: they answer the
            # agent with their failure instead of raising, and log their own.)
            logger.warning("tool %s failed for %s", name, self.agent, exc_info=exc)
            await self.emit(
                AgentEvent(
                    type="tool_error",
                    message=f"{name} failed: {exc}",
                    data={"agent": self.agent, "tool": name, **self.data},
                )
            )
            raise


def retrying(max_retries: int = 3) -> ModelRetryMiddleware:
    """LangChain's retry, with our predicate: transient failures are worth another
    attempt, running out of credits never is."""
    return ModelRetryMiddleware(
        max_retries=max_retries,
        retry_on=_retryable,
        initial_delay=0.5,
        max_delay=8.0,
        backoff_factor=2.0,
    )


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, ProviderCreditsError | StoppedError | TimeoutError):
        return False
    return is_transient(exc) or _tool_use_failed(exc)


def out_of_credits(exc: Exception) -> bool:
    """True when the provider refused for money: 402 with no credits, or
    OpenRouter's 403 "Key limit exceeded" once the key hits its own cap, which is
    the ceiling the demo relies on. Other 403s (moderation, a bad key) stay
    generic failures."""
    status = _status_of(exc)
    if status == 402:
        return True
    return status == 403 and "limit exceeded" in _body_of(exc).lower()


def _tool_use_failed(exc: Exception) -> bool:
    """Groq's ``400 tool_use_failed``: the model emitted a tool call the server
    could not parse. It is stochastic, so a fresh generation usually works."""
    if _status_of(exc) != 400:
        return False
    return "tool_use_failed" in _body_of(exc)


def _status_of(exc: Exception) -> int | None:
    for attribute in ("status_code", "http_status"):
        status = getattr(exc, attribute, None)
        if isinstance(status, int):
            return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _body_of(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    text = getattr(response, "text", None)
    return text if isinstance(text, str) else str(exc)


def _estimate_call(messages: list[Any], tools: Any) -> int:
    """Estimate what a call will cost against the tokens-per-minute ceiling: the
    messages and tool schemas going up, plus a reservation for the reply.
    Approximate by design, and paired with a per-model safety margin."""
    text = json.dumps([str(getattr(m, "content", m)) for m in messages])
    text += json.dumps(str(tools or ""))
    return len(text) // _CHARS_PER_TOKEN + _OUTPUT_TOKEN_RESERVATION


def _usage_of(response: ModelResponse | AIMessage) -> dict[str, Any] | None:
    """Tokens and cost for one call. ``usage_metadata`` carries the counts;
    OpenRouter's dollar cost rides along in the raw ``usage`` block, which
    LangChain keeps under ``response_metadata``."""
    message = _message_of(response)
    if message is None:
        return None
    counts = message.usage_metadata or {}
    raw = (message.response_metadata or {}).get("token_usage") or {}
    return {
        "input_tokens": counts.get("input_tokens") or raw.get("prompt_tokens"),
        "output_tokens": counts.get("output_tokens") or raw.get("completion_tokens"),
        "total_tokens": counts.get("total_tokens") or raw.get("total_tokens"),
        "cost_usd": raw.get("cost"),
        "model": (message.response_metadata or {}).get("model_name"),
    }


def _reasoning_of(chunk: dict) -> str:
    """The thinking in one raw streamed chunk, if the provider sent any."""
    choices = chunk.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    thought = delta.get(REASONING)
    return thought if isinstance(thought, str) else ""


def _message_of(response: ModelResponse | AIMessage) -> AIMessage | None:
    if isinstance(response, AIMessage):
        return response
    result = getattr(response, "result", None) or []
    for item in result:
        if isinstance(item, AIMessage):
            return item
    return None
