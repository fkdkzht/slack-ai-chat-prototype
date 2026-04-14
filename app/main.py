from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app.settings import Settings, get_settings
from app.cleansing.demask import demask_text_policy_p0
from app.cleansing.presidio import cleanse_text_presidio
from app.slack.events import parse_message_event
from app.slack.reply import format_first_reply, post_thread_reply
from app.slack.verify import SlackVerificationError, verify_slack_request

app = FastAPI()


@app.get("/healthz")
def healthz(_settings: Settings = Depends(get_settings)) -> dict:
    return {"ok": True}


@app.post("/slack/events")
async def slack_events(
    request: Request,
    settings: Settings = Depends(get_settings),
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
    cleansing = cleanse_text_presidio(ev.text)

    llm_text = f"(sanitized) {cleansing.sanitized_text}"
    restored = demask_text_policy_p0(llm_text, cleansing.mask_map)

    summary_parts = [f"{k} x{v}" for k, v in sorted(cleansing.mask_summary.items())]
    summary = "Masked: " + (", ".join(summary_parts) if summary_parts else "NONE")

    thread_ts = ev.thread_ts or ev.ts
    reply_text = format_first_reply(mask_summary=cleansing.mask_summary, answer_text=restored)
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
            "mask_summary": cleansing.mask_summary,
            "mask_summary_text": summary,
            "reply_text": restored,
            "posted": True,
        },
    }

