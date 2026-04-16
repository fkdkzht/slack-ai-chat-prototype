from app.cleansing.demask import demask_text_policy_p0


def test_demask_restores_all_presidio_style_tokens() -> None:
    text = "Hello <PERSON_1>. Your card is <CREDIT_CARD_1>."
    mask_map = {"<PERSON_1>": "Alice", "<CREDIT_CARD_1>": "4111 1111 1111 1111"}
    out = demask_text_policy_p0(text, mask_map)
    assert "Alice" in out
    assert "4111 1111 1111 1111" in out


def test_demask_ignores_non_presidio_tokens() -> None:
    text = "token={{EMAIL}}"
    mask_map = {"{{EMAIL}}": "alice@example.com"}
    out = demask_text_policy_p0(text, mask_map)
    assert out == text

