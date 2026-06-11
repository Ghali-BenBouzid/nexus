from app.core.config import Settings


def test_settings_has_llm_provider_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    s = Settings(_env_file=None)
    assert s.llm_provider == "gemini"
    assert s.llm_rate_limit_per_min == 25
    assert s.groq_api_key is None
    assert s.llm_model is None
