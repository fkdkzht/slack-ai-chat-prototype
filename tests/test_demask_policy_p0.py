from app.cleansing.demask import demask_text_policy_p0


def test_demask_restores_person_but_not_credit_card() -> None:
    text = "Hello <PERSON_1>. Your card is <CREDIT_CARD_1>."
    mask_map = {"<PERSON_1>": "Alice", "<CREDIT_CARD_1>": "4111 1111 1111 1111"}
    out = demask_text_policy_p0(text, mask_map)
    assert "Alice" in out
    assert "<CREDIT_CARD_1>" in out

