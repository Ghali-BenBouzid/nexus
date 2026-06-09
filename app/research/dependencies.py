from app.agents.provider import GeminiProvider
from app.agents.search import TavilyBackend
from app.core.config import settings


def get_provider() -> GeminiProvider:
    """A fresh, client-less provider (an async context manager the job opens)."""
    return GeminiProvider(
        api_key=settings.gemini_api_key or "", model=settings.model_name
    )


def get_search_backend() -> TavilyBackend:
    """A fresh, client-less search backend (opened by the job)."""
    return TavilyBackend(api_key=settings.tavily_api_key or "")
