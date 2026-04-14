from app.cleansing.presidio import cleanse_text_presidio


def test_cleansing_masks_email_and_phone() -> None:
    text = "Email me at alice@example.com or call +1 415 555 2671."
    r = cleanse_text_presidio(text)

    assert "<PHONE_NUMBER_1>" in r.sanitized_text
    assert "<EMAIL_ADDRESS_1>" in r.sanitized_text
    assert r.mask_map["<EMAIL_ADDRESS_1>"] == "alice@example.com"
    assert r.mask_summary["EMAIL_ADDRESS"] == 1
    assert r.mask_summary["PHONE_NUMBER"] == 1

