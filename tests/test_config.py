import ssl

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
    assert s.max_concurrency == s.cap  # every researcher of a run starts at once
    assert s.default_budget_usd == 0.50


def test_a_database_url_copied_from_a_provider_is_made_async(monkeypatch):
    """Supabase and Neon hand out libpq URLs. Without a driver SQLAlchemy picks
    psycopg2, which the async engine cannot use, and asyncpg rejects libpq's
    sslmode and channel_binding (SSL comes from DATABASE_SSL instead)."""
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    cases = {
        "postgresql://u:p@db.example.com:5432/postgres": (
            "postgresql+asyncpg://u:p@db.example.com:5432/postgres"
        ),
        "postgres://u:p@db.example.com/postgres?sslmode=require&channel_binding=x": (
            "postgresql+asyncpg://u:p@db.example.com/postgres"
        ),
        "postgresql+asyncpg://u:p@db.example.com/postgres": (
            "postgresql+asyncpg://u:p@db.example.com/postgres"
        ),
        "sqlite+aiosqlite:///:memory:": "sqlite+aiosqlite:///:memory:",
    }
    for given, expected in cases.items():
        monkeypatch.setenv("DATABASE_URL", given)
        assert Settings(_env_file=None).database_url == expected


def test_ssl_trusts_supabase_root_and_still_verifies(monkeypatch):
    """Supabase's pooler chains to Supabase's own root, which no system store
    holds, so a plain verified connection failed. The root is added to the
    public ones, not swapped for them: the Neon backup still verifies too."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/d")
    monkeypatch.setenv("DATABASE_SSL", "true")
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    context = Settings(_env_file=None).db_connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert not context.verify_flags & ssl.VERIFY_X509_STRICT  # Supabase's root fails it
    names = [dict(f[0] for f in ca["subject"]) for ca in context.get_ca_certs()]
    assert any(name.get("commonName") == "Supabase Root 2021 CA" for name in names)
