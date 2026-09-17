from typing import Literal

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
    # Sub-questions, so researchers, per run. The planner picks how many the
    # question needs and stops there, so this is a ceiling for broad questions,
    # not a target: a narrow one still gets one or two. Raising it widens a
    # report's breadth and costs about that much more per run.
    cap: int = 6  # max sub-questions
    max_iters: int = 3  # max tool rounds per researcher
    # Researchers run in parallel on a paid key. On a free tier, drop this to 1:
    # parallel researchers split a small tokens-per-minute budget and time out.
    # Matches cap, so every researcher of a run starts at once and they share the
    # same research_budget window. OpenRouter's limits (1000 rpm, 10M tpm) are far
    # above this; on a free tier, drop it to 1.
    max_concurrency: int = 6  # simultaneous researchers
    planner_retry_cap: int = 2
    # Soft deadline for the research fan-out: once it passes, each researcher stops
    # searching and submits what it has, so a slow (reasoning) model still yields a
    # report instead of a timeout. per_researcher_timeout stays the hard stop for a
    # researcher stuck inside a single call.
    research_budget: float = 120.0  # seconds
    per_researcher_timeout: float = 150.0  # seconds
    # The writer's own limit: past it, the report is assembled straight from the
    # findings (claims and citations intact) instead of losing them to a timeout.
    writer_timeout: float = 150.0  # seconds
    # Whole-job backstop for bugs, above the budgets that normally bound a run
    # (research ~150 s + writer 150 s, plus planning on the one-shot path).
    global_timeout: float = 420.0  # seconds
    # Supervisor tool-loop budget: how many gather-then-decide rounds it may take
    # before it must commit. Kept low: nothing else happens until it decides, so a
    # follow-up stays responsive; it usually decides in one round.
    supervisor_max_iters: int = 4

    # Where jobs run (routing a message, planning, research, composing). "redis":
    # the API only enqueues them and the worker process runs them
    # (`arq app.worker.WorkerSettings`), so no model call lives inside an HTTP
    # request and redeploying the API never kills a run. "inline": they run in the
    # API process after the response, for the tests or a one-process setup.
    job_queue: Literal["redis", "inline"] = "redis"
    redis_url: str = "redis://localhost:6379"
    worker_max_jobs: int = 10  # jobs one worker runs at once

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
    # model family from the one under test, to limit self-preference bias. No
    # default: judging refuses to start without it, so the judge behind a score is
    # always one someone chose. Optional here because only the evals need it.
    eval_judge_model: str | None = None

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
