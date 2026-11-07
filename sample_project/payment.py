def validate_payment(amount: float, card_number: str) -> bool:
    """Demo-only validation. Never use this for real payment processing."""
    if amount <= 0:
        return False
    if not card_number or len(card_number) < 12:
        return False
    return True
