from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_url: str = Field(default="https://feedbot.io", alias="FEEDBOT_API_URL")
    api_key: str = Field(default="", alias="FEEDBOT_API_KEY")
