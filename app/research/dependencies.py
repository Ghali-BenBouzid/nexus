from fastapi import HTTPException

from app.agents.openai_provider import OpenAICompatibleProvider
from app.agents.provider import LLMProvider
from app.agents.rate_limit import RateLimiter
from app.agents.retry import RetryPolicy
from app.agents.search import TavilyBackend
from app.core.config import settings

# Each preset: (base_url, default_model, settings-attr holding the key). All run
# through the one OpenAI-compatible adapter (so they share the limiter, retry, and
# retry-after handling); Gemini exposes an OpenAI-compatible endpoint too.
#
# Default = gemini-3.1-flash-lite. Its free-tier profile is the inverse of Groq's:
# a low ~15 RPM (which the request side of the RateLimiter paces) but a very high
# ~250k TPM, so the token starvation that throttles the Groq models is a non-issue,
# and Gemini has reliable native function-calling (no llama-style tool_use_failed).
# Chosen over gemini-2.5-flash for its far higher free ceiling: 500 requests/day
# vs 20 (one research run is ~10-15 requests, so 2.5-flash allows ~1 run/day).
_OPENAI_PRESETS = {
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
# Conservative fallback for a provider/model not in the table above.
_DEFAULT_RATE_LIMIT = (30, 6_000)
# Pace under the published ceilings, leaving headroom so approximate token
# estimates and extra requests from retries (e.g. Gemini's frequent 503s) don't
# tip a run over the limit into a 429.
_TPM_SAFETY = 0.9
_RPM_SAFETY = 0.8


def _rate_limiter(provider: str, model: str) -> RateLimiter:
    rpm, tpm = _RATE_LIMITS.get(provider, {}).get(model, _DEFAULT_RATE_LIMIT)
    return RateLimiter(rpm=max(1, int(rpm * _RPM_SAFETY)), tpm=int(tpm * _TPM_SAFETY))


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )


def get_provider() -> LLMProvider:
    """A fresh, client-less provider (an async context manager the job opens).

    Dispatches on settings.llm_provider; fails fast with a clear 503 when the
    selected provider's key is missing.
    """
    provider = settings.llm_provider

    if provider in _OPENAI_PRESETS:
        base_url, default_model, key_attr = _OPENAI_PRESETS[provider]
        api_key = getattr(settings, key_attr)
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail=f"Research is not configured (missing {provider} API key).",
            )
        model = settings.llm_model or default_model
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=model,
            api_key=api_key,
            retry=_retry_policy(),
            rate_limiter=_rate_limiter(provider, model),
        )

    raise HTTPException(status_code=503, detail=f"Unknown LLM provider: {provider}")


def get_search_backend() -> TavilyBackend:
    """A fresh, client-less search backend (opened by the job)."""
    if not settings.tavily_api_key:
        raise HTTPException(
            status_code=503,
            detail="Research is not configured (missing search API key).",
        )
    return TavilyBackend(api_key=settings.tavily_api_key, retry=_retry_policy())
