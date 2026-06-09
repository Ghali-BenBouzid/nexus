from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # database settings
    database_url: str

    # auth settings
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int

    # agent / provider settings
    gemini_api_key: str | None = None
    tavily_api_key: str | None = None
    model_name: str = "gemini-2.5-flash"

    # orchestration knobs (12-factor: env-overridable defaults)
    cap: int = 5  # max sub-questions
    max_iters: int = 5  # max tool rounds per researcher
    max_concurrency: int = 3  # simultaneous researchers
    planner_retry_cap: int = 2
    per_researcher_timeout: float = 120.0  # seconds
    global_timeout: float = 300.0  # seconds, whole-job backstop


settings = Settings()
