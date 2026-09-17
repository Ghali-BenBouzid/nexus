from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # database settings
    database_url: str
    database_ssl: bool = False  # True for managed Postgres (Neon); off locally

    # auth settings
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # CORS: comma-separated allowed frontend origins (empty = no browser access)
    cors_origins: str = ""

    # Demo accounts. There is no public signup: an admin creates each account with
    # `python -m app.admin` and hands out its invite link. These are the defaults
    # for a new account; each one can be topped up or extended later.
    frontend_url: str = "http://localhost:5173"  # base of the invite links
    default_budget_usd: float = 0.50
    default_access_days: int = 14  # 0 = never expires

    # agent / provider settings
    gemini_api_key: str | None = None
    tavily_api_key: str | None = None

    # LLM provider selection: openrouter | gemini | groq | cerebras | sambanova
    llm_provider: str = "openrouter"
    llm_model: str | None = None  # overrides the provider's default model
    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    sambanova_api_key: str | None = None
    # Pace all LLM calls under the active provider's free RPM (set below it).
    llm_rate_limit_per_min: int = 25

    # orchestration knobs (12-factor: env-overridable defaults). Kept small so a
    # run stays quick and cheap; a future "deep research" mode raises these.
    cap: int = 3  # max sub-questions
    max_iters: int = 3  # max tool rounds per researcher
    # Researchers run in parallel on a paid key. On a free tier, drop this to 1:
    # parallel researchers split a small tokens-per-minute budget and time out.
    max_concurrency: int = 3  # simultaneous researchers
    planner_retry_cap: int = 2
    per_researcher_timeout: float = 150.0  # seconds
    global_timeout: float = 300.0  # seconds, whole-job backstop
    # Supervisor tool-loop budget: how many gather-then-decide rounds it may take
    # before it must commit. Kept low: it runs synchronously in the request, so a
    # follow-up stays responsive; it usually decides in one round.
    supervisor_max_iters: int = 4

    # transient-error retry/backoff for provider & search calls. Also re-rolls a
    # stochastic 400 tool_use_failed (a malformed tool call usually parses on a
    # fresh generation) — rare on the default model, common on llama-family ones.
    retry_max_attempts: int = 3
    retry_base_delay: float = 0.5  # seconds before the first retry
    retry_max_delay: float = 8.0  # backoff ceiling

    # observability (LangSmith). Off by default: the @traceable decorators stay in
    # the hot path year-round but are inert no-ops until tracing is switched on with
    # a key. configure_tracing() bridges these into the LANGSMITH_* env the SDK reads.
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "nexus"
    langsmith_endpoint: str | None = None  # set for self-hosted / EU LangSmith

    # Evals (python -m app.evals): the judge that scores recorded runs, any
    # OpenRouter model id, billed to OPENROUTER_API_KEY. Deliberately a different
    # model family from the one under test, to limit self-preference bias.
    eval_judge_model: str = "openai/gpt-5-mini"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def db_connect_args(self) -> dict[str, object]:
        # asyncpg (unlike psycopg2) won't read sslmode from the URL; pass ssl here.
        return {"ssl": True} if self.database_ssl else {}


settings = Settings()
