from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://feedbot:feedbot@localhost:5432/feedbot",
        alias="DATABASE_URL",
    )
    secret_key: str = Field(default="dev-secret", alias="FEEDBOT_SECRET_KEY")
    log_level: str = Field(default="INFO", alias="FEEDBOT_LOG_LEVEL")
