from payment import validate_payment


def test_accepts_valid_payment():
    assert validate_payment(10.0, "4111111111111111") is True


def test_rejects_zero_amount():
    assert validate_payment(0, "4111111111111111") is False
