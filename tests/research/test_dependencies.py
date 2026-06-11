import pytest
from fastapi import HTTPException

from app.agents.openai_provider import OpenAICompatibleProvider
from app.agents.provider import GeminiProvider
from app.core.config import settings
from app.research.dependencies import get_provider


def test_get_provider_returns_gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "key")
    assert isinstance(get_provider(), GeminiProvider)


def test_get_provider_returns_openai_compatible_for_groq(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "key")
    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "llama-3.3-70b-versatile"


def test_get_provider_503_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(HTTPException) as exc:
        get_provider()
    assert exc.value.status_code == 503
