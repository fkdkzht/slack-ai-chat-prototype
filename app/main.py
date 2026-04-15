import json
import logging
import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

from app.llm.gemini import generate_reply
from app.logging_ import configure_app_logging, slack_ingest_log
from app.orchestrator import handle_user_message
from app.settings import Settings, get_settings
from app.session.store_firestore import FirestoreSessionStore
from app.slack.events import parse_message_event
from app.slack.reply import format_first_reply, post_thread_reply
from app.slack.verify import SlackVerificationError, verify_slack_request

_log = logging.getLogger("slack_ai_chat")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    configure_app_logging(os.environ.get("APP_ENV", "dev"))
    yield


app = FastAPI(lifespan=_lifespan)


@lru_cache(maxsize=16)
def _session_store(project_id: str, database: str, ttl_hours: int) -> FirestoreSessionStore:
    return FirestoreSessionStore(project_id=project_id, database=database, ttl_hours=ttl_hours)


def get_session_store(settings: Settings = Depends(get_settings)) -> FirestoreSessionStore:
    return _session_store(settings.gcp_project_id, settings.firestore_database, settings.session_ttl_hours)


def _slack_message_is_bot_traffic(payload: dict, event: dict) -> bool:
    if event.get("bot_id"):
        return True
    uid = event.get("user")
    if not uid:
        return True
    for auth in payload.get("authorizations") or []:
        if auth.get("is_bot") and auth.get("user_id") == uid:
            return True
    return False


def _process_slack_message_event(
    payload: dict,
    settings: Settings,
    store: FirestoreSessionStore,
) -> None:
    event_id = str(payload.get("event_id") or "")
    try:
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

        thread_ts = ev.thread_ts or ev.ts
        reply_text = format_first_reply(mask_summary=mask_summary, answer_text=restored)
        post_thread_reply(
            bot_token=settings.slack_bot_token,
            channel_id=ev.channel_id,
            thread_ts=thread_ts,
            text=reply_text,
        )
        slack_ingest_log(
            settings.app_env,
            "slack_message_done",
            outcome="posted",
            event_id=event_id or None,
            text_len=len(ev.text),
        )
    except Exception as e:
        slack_ingest_log(
            settings.app_env,
            "slack_message_failed",
            outcome="handler_error",
            event_id=event_id or None,
            exc_type=type(e).__name__,
        )
        _log.exception("slack_message_failed event_id=%s", event_id or "-")


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
    background_tasks: BackgroundTasks,
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
        slack_ingest_log(settings.app_env, "slack_verify_failed", outcome="verify_failed", detail=type(e).__name__)
        raise HTTPException(status_code=401, detail=str(e)) from e

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        slack_ingest_log(settings.app_env, "slack_bad_json", outcome="bad_json", detail=type(e).__name__)
        raise HTTPException(status_code=400, detail="invalid json") from e

    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    if payload.get("type") != "event_callback":
        return {"ok": True}

    event = payload.get("event", {})
    eid = payload.get("event_id")
    if event.get("type") != "message":
        slack_ingest_log(settings.app_env, "slack_skip", outcome="skip_not_message", event_id=eid)
        return {"ok": True}
    if not event.get("user"):
        slack_ingest_log(settings.app_env, "slack_skip", outcome="skip_no_user", event_id=eid)
        return {"ok": True}
    # Only plain user messages (Slack omits subtype). Anything else includes bot/system events.
    if event.get("subtype") not in (None, ""):
        slack_ingest_log(settings.app_env, "slack_skip", outcome="skip_subtype", event_id=eid, subtype=event.get("subtype"))
        return {"ok": True}
    if _slack_message_is_bot_traffic(payload, event):
        slack_ingest_log(settings.app_env, "slack_skip", outcome="skip_bot_traffic", event_id=eid)
        return {"ok": True}

    delivery_id = str(payload.get("event_id") or "")
    if not store.try_claim_slack_event_delivery(delivery_id):
        slack_ingest_log(settings.app_env, "slack_skip", outcome="dedupe", event_id=delivery_id or None)
        return {"ok": True}

    # Slack retries if we do not respond with HTTP 2xx within ~3s; ack first, then process.
    slack_ingest_log(settings.app_env, "slack_queued", outcome="queued", event_id=delivery_id or None)
    background_tasks.add_task(_process_slack_message_event, payload, settings, store)
    return {"ok": True}

