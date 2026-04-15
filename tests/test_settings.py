from app.settings import Settings


def test_settings_has_defaults() -> None:
    s = Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    assert s.firestore_database == "default"
    assert s.session_ttl_hours == 24
    assert s.gemini_model


def test_demo_settings_defaults() -> None:
    s = Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )
    assert s.demo_mode is False
    assert s.gemini_filter_model
    assert s.gemini_chat_model

