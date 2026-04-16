# Verification: Firestore session, Slack thread, mask path

Use this checklist when validating behavior in a real environment. Tracking issue: GitHub `#1` (label `verify`).

## Thread equals session

- Code: `app/slack/events.py` — `session_id` is `{channel_id}:{thread_ts or ts}`.
- Expectation: all messages in the same Slack thread share one Firestore document under `sessions/{session_id}`.

## Firestore document shape

Open GCP Console → Firestore → collection `sessions` → document ID = `session_id` (e.g. `D0123:1699999999.0009`).

After two user turns in the same thread:

| Field | Expected |
|-------|----------|
| `history` | Two or more entries; each user `text` is **sanitized** (placeholder tokens), not raw secrets. |
| `mask_map` | Tokens → values for restoration (Presidio path); grows across turns. |
| `ttl_at` | Refreshed on each update. |

## Demo mode (`demo_mode=true`)

- Sheets webhook receives `sanitized_text` and `pii_dictionary` (see `app/main.py` export hook).
- Firestore `history` must still contain **only** sanitized text; compare payload vs `history` for consistency.

## Security

Do not enable logging of full user text or `mask_map` values in production.

## Automated invariants

See `tests/test_orchestrator_unit.py` — tests assert the chat model never receives raw PII when a `filter_fn` is used and that persisted history stays sanitized.
