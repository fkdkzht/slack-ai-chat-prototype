from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.llm.gemini import generate_reply
from app.orchestrator import handle_user_message
from app.settings import Settings, get_settings
from app.session.store_firestore import FirestoreSessionStore
from app.slack.events import parse_message_event
from app.slack.reply import format_first_reply, post_thread_reply
from app.slack.verify import SlackVerificationError, verify_slack_request

app = FastAPI()


@lru_cache(maxsize=16)
def _session_store(project_id: str, database: str, ttl_hours: int) -> FirestoreSessionStore:
    return FirestoreSessionStore(project_id=project_id, database=database, ttl_hours=ttl_hours)


def get_session_store(settings: Settings = Depends(get_settings)) -> FirestoreSessionStore:
    return _session_store(settings.gcp_project_id, settings.firestore_database, settings.session_ttl_hours)


def _health_payload(_settings: Settings) -> dict:
    return {"ok": True}


@app.get("/healthz")
def healthz(_settings: Settings = Depends(get_settings)) -> dict:
    return _health_payload(_settings)


@app.get("/health")
def health(_settings: Settings = Depends(get_settings)) -> dict:
    """Use this path for probes on Cloud Run: the default *.run.app edge may intercept ``/healthz`` (lowercase)."""
    return _health_payload(_settings)


@app.post("/slack/events")
async def slack_events(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FirestoreSessionStore = Depends(get_session_store),
    x_slack_request_timestamp: str = Header(alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str = Header(alias="X-Slack-Signature"),
) -> dict:
    body = await request.body()
    try:
        verify_slack_request(
            signing_secret=settings.slack_signing_secret,
            timestamp=x_slack_request_timestamp,
            signature=x_slack_signature,
            body=body,
        )
    except SlackVerificationError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    payload = await request.json()

    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    if payload.get("type") != "event_callback":
        return {"ok": True}

    if payload.get("event", {}).get("type") != "message":
        return {"ok": True}

    ev = parse_message_event(payload)
    session_id = ev.session_id
    state = store.get(session_id) or store.new_state(session_id)

    def gen_fn(messages: list[dict[str, str]]) -> str:
        return generate_reply(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            messages=messages,
        )

    state, mask_summary, restored = handle_user_message(
        state=state,
        user_text=ev.text,
        user_ts=ev.ts,
        generate_reply_fn=gen_fn,
        ttl_hours=settings.session_ttl_hours,
    )
    store.upsert(state)

    summary_parts = [f"{k} x{v}" for k, v in sorted(mask_summary.items())]
    summary = "Masked: " + (", ".join(summary_parts) if summary_parts else "NONE")

    thread_ts = ev.thread_ts or ev.ts
    reply_text = format_first_reply(mask_summary=mask_summary, answer_text=restored)
    post_thread_reply(
        bot_token=settings.slack_bot_token,
        channel_id=ev.channel_id,
        thread_ts=thread_ts,
        text=reply_text,
    )

    return {
        "ok": True,
        "debug": {
            "session_id": ev.session_id,
            "mask_summary": mask_summary,
            "mask_summary_text": summary,
            "reply_text": restored,
            "posted": True,
        },
    }

