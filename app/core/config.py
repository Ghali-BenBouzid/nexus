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

    # agent / provider settings
    gemini_api_key: str | None = None
    tavily_api_key: str | None = None
    model_name: str = "gemini-2.5-flash"

    # LLM provider selection: gemini | groq | cerebras | sambanova
    llm_provider: str = "gemini"
    llm_model: str | None = None  # overrides the provider's default model
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    sambanova_api_key: str | None = None
    # Pace all LLM calls under the active provider's free RPM (set below it).
    llm_rate_limit_per_min: int = 25

    # orchestration knobs (12-factor: env-overridable defaults)
    cap: int = 5  # max sub-questions
    max_iters: int = 5  # max tool rounds per researcher
    max_concurrency: int = 3  # simultaneous researchers
    planner_retry_cap: int = 2
    per_researcher_timeout: float = 120.0  # seconds
    global_timeout: float = 300.0  # seconds, whole-job backstop

    # transient-error retry/backoff for provider & search calls
    retry_max_attempts: int = 3
    retry_base_delay: float = 0.5  # seconds before the first retry
    retry_max_delay: float = 8.0  # backoff ceiling

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
