from fastapi.testclient import TestClient

from app.settings import Settings, get_settings

def test_healthz() -> None:
    from app.main import app

    app.dependency_overrides[get_settings] = lambda: Settings(
        slack_signing_secret="x",
        slack_bot_token="x",
        gcp_project_id="x",
        gemini_api_key="x",
    )

    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"ok": True}

