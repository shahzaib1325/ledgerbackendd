from datetime import date


def format_invoice_number(prefix: str, year: int, sequence: int) -> str:
    """
    Formats an invoice/PO number in the standard pattern.

    Example: format_invoice_number("INV", 2026, 42) → "INV-2026-00042"
    """
    return f"{prefix}-{year}-{sequence:05d}"


def current_year() -> int:
    return date.today().year
