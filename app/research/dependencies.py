from fastapi import HTTPException

from app.agents.provider import GeminiProvider
from app.agents.retry import RetryPolicy
from app.agents.search import TavilyBackend
from app.core.config import settings


def _retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
    )


def get_provider() -> GeminiProvider:
    """A fresh, client-less provider (an async context manager the job opens).

    Fail fast with a clear 503 when no key is configured, rather than letting the
    background job die with an opaque SDK auth error half-way through.
    """
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=503, detail="Research is not configured (missing LLM API key)."
        )
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.model_name,
        retry=_retry_policy(),
    )


def get_search_backend() -> TavilyBackend:
    """A fresh, client-less search backend (opened by the job)."""
    if not settings.tavily_api_key:
        raise HTTPException(
            status_code=503,
            detail="Research is not configured (missing search API key).",
        )
    return TavilyBackend(api_key=settings.tavily_api_key, retry=_retry_policy())
