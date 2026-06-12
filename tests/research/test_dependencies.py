import pytest
from fastapi import HTTPException

from app.agents.openai_provider import OpenAICompatibleProvider
from app.core.config import settings
from app.research.dependencies import get_provider


def test_get_provider_returns_openai_compatible_for_gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "key")
    monkeypatch.setattr(settings, "llm_model", None)
    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert (
        provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert provider.model == "gemini-3.1-flash-lite"


def test_get_provider_returns_openai_compatible_for_groq(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "key")
    monkeypatch.setattr(settings, "llm_model", None)
    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "openai/gpt-oss-120b"


def test_get_provider_503_when_key_missing(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(HTTPException) as exc:
        get_provider()
    assert exc.value.status_code == 503
