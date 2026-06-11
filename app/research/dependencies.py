from fastapi import HTTPException

from app.agents.openai_provider import OpenAICompatibleProvider
from app.agents.provider import GeminiProvider, LLMProvider
from app.agents.retry import RetryPolicy
from app.agents.search import TavilyBackend
from app.core.config import settings

# Each preset: (base_url, default_model, settings-attr holding the key).
_OPENAI_PRESETS = {
    "groq": (
        "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile",
        "groq_api_key",
    ),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b", "cerebras_api_key"),
    "sambanova": (
        "https://api.sambanova.ai/v1",
        "Meta-Llama-3.3-70B-Instruct",
        "sambanova_api_key",
    ),
}


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

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise HTTPException(
                status_code=503,
                detail="Research is not configured (missing LLM API key).",
            )
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.model_name,
            retry=_retry_policy(),
        )

    if provider in _OPENAI_PRESETS:
        base_url, default_model, key_attr = _OPENAI_PRESETS[provider]
        api_key = getattr(settings, key_attr)
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail=f"Research is not configured (missing {provider} API key).",
            )
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=settings.llm_model or default_model,
            api_key=api_key,
            retry=_retry_policy(),
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
