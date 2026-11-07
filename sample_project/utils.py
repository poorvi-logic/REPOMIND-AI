def format_currency(amount: float) -> str:
    return f"₹{amount:,.2f}"


def normalise_amount(value: float) -> float:
    return round(value, 2)
