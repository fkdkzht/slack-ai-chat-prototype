from app.slack.reply import format_first_reply


def test_format_first_reply_includes_summary_and_answer() -> None:
    text = format_first_reply(mask_summary={"EMAIL_ADDRESS": 1}, answer_text="hello")
    assert "Masked:" in text
    assert "hello" in text

