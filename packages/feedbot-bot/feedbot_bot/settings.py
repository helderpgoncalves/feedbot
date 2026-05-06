from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Settings for the global Feedbot Telegram bot.

    The bot uses a server-side shared secret (FEEDBOT_BOT_TOKEN) to call
    /v1/internal/* endpoints. It does **not** use end-user API keys: chat→project
    routing happens server-side via the chat_links table.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_url: str = Field(default="http://localhost:8000", alias="FEEDBOT_API_URL")
    bot_token: str = Field(default="", alias="FEEDBOT_BOT_TOKEN")
    telegram_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
