import logging

import pytest

from app.logging_ import configure_app_logging, slack_ingest_log


def test_slack_ingest_prod_skips_verbose_outcomes(caplog: pytest.LogCaptureFixture) -> None:
    configure_app_logging("prod")
    caplog.set_level(logging.INFO, logger="slack_ai_chat")
    slack_ingest_log("prod", "slack_skip", outcome="dedupe", event_id="Ev1")
    assert not caplog.records


def test_slack_ingest_dev_logs_skip(caplog: pytest.LogCaptureFixture) -> None:
    configure_app_logging("dev")
    caplog.set_level(logging.DEBUG, logger="slack_ai_chat")
    slack_ingest_log("dev", "slack_skip", outcome="dedupe", event_id="Ev1")
    assert any("dedupe" in r.message for r in caplog.records)
