from typing import Any

from fastapi import HTTPException

from app.agents.model import build_model
from app.agents.rate_limit import RateLimiter
from app.agents.retry import RetryPolicy
from app.agents.search import SelfHostedBackend, TavilyBackend
from app.agents.tools import SearchBackend
from app.core.config import Effort, settings

# Each preset: (base_url, default_model, settings-attr holding the key). All run
# through the one OpenAI-compatible adapter (so they share the limiter, retry, and
# retry-after handling); Gemini exposes an OpenAI-compatible endpoint too.
#
# Default = OpenRouter, a paid key with a hard credit limit, where each call reports
# its own cost (billed to the demo account by MeteredProvider). Its default model is
# gemini-3.1-flash-lite, the model the prompts were tuned on (USD 0.25 / 1.50 per
# million input / output tokens); LLM_MODEL swaps it for any OpenRouter model id.
# The free-tier presets below stay for local development.
_OPENAI_PRESETS = {
    "openrouter": (
        "https://openrouter.ai/api/v1",
        "google/gemini-3.1-flash-lite",
        "openrouter_api_key",
    ),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-3.1-flash-lite",
        "gemini_api_key",
    ),
    "groq": (
        "https://api.groq.com/openai/v1",
        "openai/gpt-oss-120b",
        "groq_api_key",
    ),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b", "cerebras_api_key"),
    "sambanova": (
        "https://api.sambanova.ai/v1",
        "Meta-Llama-3.3-70B-Instruct",
        "sambanova_api_key",
    ),
}

# Extra body fields only OpenRouter understands, sent on every call.
#
# ``reasoning`` asks for the model's thinking as its own stream of deltas. On a
# reasoning model that thinking is most of the turn: the first thought arrives
# seconds before the first word of the answer, so this is what the live feed has
# to show while the answer is still being formed. Some models reason whether or
# not we ask (glm refuses to turn it off); asking is what makes it visible rather
# than silent. Its effort is set per call site (chat_model): asking with no
# effort lets glm think at its own ceiling, 70 to 114 s on a question "high"
# answered in 50 to 85 s, so that is kept for "max".
#
# ``provider`` picks which of the model's ~30 upstreams serves the call, and on
# a stream that choice is something the user watches. Sorting by throughput
# ranked upstreams on their recent median, and kept sending most calls to one
# that was degraded (12 tok/s, 9 s to the first token, over a minute for 700
# tokens) because its median still led. Sorting by latency alone settled on a
# premium upstream at three times the price. So: the cheapest upstream that is
# fast right now. The performance floors move an upstream that misses them to
# the back of the line rather than excluding it, so a call never fails on them,
# and none of it is priced for one model: changing LLM_MODEL needs nothing else.
# Measured on the same 700-token call: 64-68 s before, 4-11 s after.
_OPENROUTER_BODY: dict[str, Any] = {
    "provider": {
        "sort": "price",
        "preferred_min_throughput": {"p50": 80, "p90": 50},
        "preferred_max_latency": {"p90": 2},
    },
}

# Free-tier (requests-per-minute, tokens-per-minute) per provider+model, from the
# providers' published rate-limit tables. The token-aware RateLimiter paces calls
# under these so a multi-researcher fan-out never bursts into a 429. TPM is the
# binding constraint on Groq's free tier.
_RATE_LIMITS: dict[str, dict[str, tuple[int, int]]] = {
    "gemini": {
        # Free tier (RPM is the binding limit, not TPM; daily cap is RPD).
        "gemini-3.1-flash-lite": (15, 250_000),  # RPD 500
        "gemini-2.5-flash": (5, 250_000),  # RPD only 20 -> ~1 run/day
    },
    "groq": {
        "meta-llama/llama-4-scout-17b-16e-instruct": (30, 30_000),
        "llama-3.3-70b-versatile": (30, 12_000),
        "openai/gpt-oss-120b": (30, 8_000),
        "openai/gpt-oss-20b": (30, 8_000),
        "qwen/qwen3-32b": (60, 6_000),
        "llama-3.1-8b-instant": (30, 6_000),
    },
}
# Per-provider fallback when the model is not in the table above. A paid
# OpenRouter key has no fixed per-minute ceiling to pace under, so pacing is
# effectively off; an upstream 429 is still retried after its Retry-After.
_PROVIDER_DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "openrouter": (1_000, 10_000_000),
}
# Conservative fallback for a free-tier provider/model not in the tables above.
_DEFAULT_RATE_LIMIT = (30, 6_000)
# Pace under the published ceilings, leaving headroom so approximate token
# estimates and extra requests from retries (e.g. Gemini's frequent 503s) don't
# tip a run over the limit into a 429.
_TPM_SAFETY = 0.9
_RPM_SAFETY = 0.8


def _rate_limiter(provider: str, model: str) -> RateLimiter:
    fallback = _PROVIDER_DEFAULT_LIMITS.get(provider, _DEFAULT_RATE_LIMIT)
    rpm, tpm = _RATE_LIMITS.get(provider, {}).get(model, fallback)
    return RateLimiter(rpm=max(1, int(rpm * _RPM_SAFETY)), tpm=int(tpm * _TPM_SAFETY))


def _retry_policy() -> RetryPolicy:
    """Backoff for the search backend. Model calls retry through middleware."""
    return RetryPolicy(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )


def get_model() -> Any:  # ChatOpenAI; see chat_model
    """The request's model, as a FastAPI dependency so tests can swap in a fake.
    A job builds the models it runs on itself (research.service.models_for)."""
    return chat_model()


def chat_model(model: str | None = None, effort: Effort = "high") -> Any:
    """The chat model an agent runs on: ``model`` (LLM_MODEL by default)
    thinking at ``effort``.

    Returned as ``Any`` on purpose: a chat model is itself a pydantic model, and
    FastAPI reads a dependency's return annotation as a request field.


    Dispatches on settings.llm_provider; fails fast with a clear 503 when the
    selected provider's key is missing. Pacing, billing, retries and error
    mapping are middleware around the agent, not the client's business, so the
    limiter this model should be paced by rides along as ``rate_limiter``.
    """
    provider = settings.llm_provider
    if provider not in _OPENAI_PRESETS:
        raise HTTPException(status_code=503, detail=f"Unknown LLM provider: {provider}")

    base_url, default_model, key_attr = _OPENAI_PRESETS[provider]
    api_key = getattr(settings, key_attr)
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"Research is not configured (missing {provider} API key).",
        )
    name = model or settings.llm_model or default_model
    # The limiter is per provider and model, and shared by everything running on
    # this model, so a fan-out paces against itself rather than each researcher
    # getting its own quota.
    return build_model(
        model=name,
        base_url=base_url,
        api_key=api_key,
        pacing=_rate_limiter(provider, name),
        # extra_body, not the ChatOpenAI ``reasoning`` field: that field switches
        # langchain-openai to OpenAI's Responses API, which OpenRouter rejects.
        extra_body=(
            {**_OPENROUTER_BODY, "reasoning": _reasoning(effort)}
            if provider == "openrouter"
            else None
        ),
    )


def _reasoning(effort: Effort) -> dict[str, Any]:
    return {"enabled": True} if effort == "max" else {"effort": effort}


def get_search_backend() -> SearchBackend:
    """A fresh, client-less search backend (opened by the job).

    The self-hosted pair wins when it is configured, because it is the one that
    costs nothing to run; Tavily stays as the fallback so a deployment without
    the services yet keeps working. Selected by what is configured rather than
    by a separate switch, so there is one fewer setting that can disagree with
    itself.
    """
    if settings.searxng_url and settings.crawl4ai_url:
        if not settings.crawl4ai_token:
            # Not a preference. Without a token Crawl4AI binds loopback inside
            # its own container, so it is unreachable from anywhere else while
            # still reporting itself healthy. Refusing here says that once,
            # instead of every page read failing to connect for reasons no log
            # explains.
            raise HTTPException(
                status_code=503,
                detail=(
                    "CRAWL4AI_TOKEN is not set. Crawl4AI only listens beyond "
                    "localhost once it has one, so without it every page read "
                    "fails to connect."
                ),
            )
        return SelfHostedBackend(
            searxng_url=settings.searxng_url,
            crawl4ai_url=settings.crawl4ai_url,
            crawl4ai_token=settings.crawl4ai_token,
            retry=_retry_policy(),
            search_timeout=settings.search_timeout,
            read_timeout=settings.page_read_timeout,
        )
    if settings.tavily_api_key:
        return TavilyBackend(api_key=settings.tavily_api_key, retry=_retry_policy())
    raise HTTPException(
        status_code=503,
        detail="Research is not configured (no search backend).",
    )
