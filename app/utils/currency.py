from decimal import ROUND_HALF_UP, Decimal


def round_currency(value: Decimal | float | str, decimals: int = 2) -> Decimal:
    """Round a monetary value using ROUND_HALF_UP to avoid banker's rounding."""
    quantize_str = Decimal(10) ** -decimals
    return Decimal(str(value)).quantize(quantize_str, rounding=ROUND_HALF_UP)
