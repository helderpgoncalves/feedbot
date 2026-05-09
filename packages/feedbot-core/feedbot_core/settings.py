import os

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
    # ``cloud`` opens self-serve signup at /v1/signup; ``self-host`` keeps the
    # deployment invite-only (the default).
    allow_signup: bool = Field(default=False, alias="FEEDBOT_ALLOW_SIGNUP")


def is_signup_enabled() -> bool:
    """Return True when ``FEEDBOT_ALLOW_SIGNUP`` is truthy.

    Read from the environment on every call so test fixtures and runtime
    flips don't get cached. Cloud closed-beta sets ``true``; self-host and
    cloud-without-signup leave it unset.
    """
    raw = os.environ.get("FEEDBOT_ALLOW_SIGNUP", "").strip().lower()
    return raw in ("true", "1", "yes")
