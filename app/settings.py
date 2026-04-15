from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_env: str = "dev"

    slack_signing_secret: str
    slack_bot_token: str

    gcp_project_id: str
    firestore_database: str = "default"
    session_ttl_hours: int = 24

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # Demo-only switches
    demo_mode: bool = False
    gemini_filter_model: str = "gemini-2.5-flash"
    gemini_chat_model: str = "gemini-2.5-flash"
    sheets_webhook_url: str | None = None


def get_settings() -> Settings:
    return Settings()

