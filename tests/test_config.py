from app.core.config import Settings


def test_settings_has_llm_provider_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    # The defaults under test, not whatever the developer's shell exports.
    for name in ("LLM_PROVIDER", "LLM_MODEL", "OPENROUTER_API_KEY", "MAX_CONCURRENCY"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.llm_provider == "openrouter"
    assert s.openrouter_api_key is None
    assert s.llm_model is None
    assert s.max_concurrency == 3
    assert s.default_budget_usd == 0.50
