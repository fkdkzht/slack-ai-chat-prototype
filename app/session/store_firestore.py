from __future__ import annotations

from datetime import UTC, datetime, timedelta

from google.cloud import firestore

from app.session.models import SessionState


def _now() -> datetime:
    return datetime.now(UTC)


def _firestore_database_id(database: str) -> str:
    """Console shows (default); Firestore API expects the database id ``default``."""
    if database == "(default)":
        return "default"
    return database


class FirestoreSessionStore:
    def __init__(self, *, project_id: str, database: str, ttl_hours: int) -> None:
        self._client = firestore.Client(
            project=project_id,
            database=_firestore_database_id(database),
        )
        self._ttl_hours = ttl_hours

    def get(self, session_id: str) -> SessionState | None:
        doc = self._client.collection("sessions").document(session_id).get()
        if not doc.exists:
            return None
        return SessionState.model_validate(doc.to_dict())

    def upsert(self, state: SessionState) -> None:
        self._client.collection("sessions").document(state.session_id).set(
            state.model_dump(mode="json"),
            merge=True,
        )

    def new_state(self, session_id: str) -> SessionState:
        now = _now()
        return SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            ttl_at=now + timedelta(hours=self._ttl_hours),
        )

