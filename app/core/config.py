from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    # database settings
    database_url: str

    # auth settings
    secret_key: str
    algorithm: str
    access_token_expire_minutes: int


settings = Settings()
