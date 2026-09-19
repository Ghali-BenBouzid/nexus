from typing import Any

from fastapi import HTTPException

from app.agents.model import build_model
from app.agents.rate_limit import RateLimiter
from app.agents.retry import RetryPolicy
from app.agents.search import TavilyBackend
from app.core.config import settings

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


def get_model() -> Any:  # ChatOpenAI; see the note below
    """The chat model the agents run on, built from settings.

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
    name = settings.llm_model or default_model
    model = build_model(model=name, base_url=base_url, api_key=api_key)
    # The limiter is per provider+model and shared by every agent on this model,
    # so a fan-out paces against itself rather than each researcher getting its
    # own quota. Carried on the model so callers need not rebuild it.
    model.rate_limiter = _rate_limiter(provider, name)
    return model


def get_search_backend() -> TavilyBackend:
    """A fresh, client-less search backend (opened by the job)."""
    if not settings.tavily_api_key:
        raise HTTPException(
            status_code=503,
            detail="Research is not configured (missing search API key).",
        )
    return TavilyBackend(api_key=settings.tavily_api_key, retry=_retry_policy())
