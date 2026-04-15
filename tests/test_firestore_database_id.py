from app.session.store_firestore import _firestore_database_id


def test_firestore_database_id_maps_console_default() -> None:
    assert _firestore_database_id("(default)") == "default"
    assert _firestore_database_id("default") == "default"
