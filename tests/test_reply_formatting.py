from app.slack.reply import format_first_reply


def test_format_first_reply_includes_summary_and_answer() -> None:
    text = format_first_reply(mask_summary={"EMAIL_ADDRESS": 1}, answer_text="hello")
    assert "Masked:" in text
    assert "hello" in text


def test_format_first_reply_omits_masked_line_when_no_items() -> None:
    text = format_first_reply(mask_summary={}, answer_text="hello")
    assert text == "hello"


def test_format_first_reply_omits_zero_counts() -> None:
    text = format_first_reply(
        mask_summary={"EMAIL_ADDRESS": 0, "PERSON": 2},
        answer_text="hello",
    )
    assert "Masked:" in text
    assert "EMAIL_ADDRESS" not in text
    assert "PERSON x2" in text


def test_format_first_reply_omits_masked_line_when_all_zero() -> None:
    text = format_first_reply(mask_summary={"EMAIL_ADDRESS": 0}, answer_text="hello")
    assert text == "hello"


def test_format_first_reply_orders_masked_items_sorted_by_key() -> None:
    text = format_first_reply(
        mask_summary={"PERSON": 1, "EMAIL_ADDRESS": 1},
        answer_text="hello",
    )
    first_line = text.splitlines()[0]
    assert first_line == "Masked: EMAIL_ADDRESS x1, PERSON x1"

