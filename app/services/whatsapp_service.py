from __future__ import annotations

from decimal import Decimal

import httpx

from app.core.config import settings

_GRAPH_URL = "https://graph.facebook.com/v20.0"

_STATUS_LABEL: dict[str, str] = {
    "draft":          "Draft",
    "confirmed":      "Confirmed",
    "partially_paid": "Partially Paid",
    "paid":           "Paid",
    "returned":       "Returned",
    "void":           "Void",
}


def _fmt(v: Decimal | str) -> str:
    n = Decimal(str(v))
    return f"{n:,.2f}"


def build_receipt_message(sale: object) -> str:
    """Build the WhatsApp receipt text from a Sale ORM object."""
    lines: list[str] = []

    lines.append(f"*Invoice: {sale.invoice_no}*")          # type: ignore[attr-defined]
    lines.append(f"Status: {_STATUS_LABEL.get(sale.status, sale.status)}")  # type: ignore[attr-defined]
    lines.append(f"Date: {sale.invoice_date}")              # type: ignore[attr-defined]
    if sale.due_date:                                       # type: ignore[attr-defined]
        lines.append(f"Due Date: {sale.due_date}")          # type: ignore[attr-defined]

    customer_name = (
        sale.walking_customer_name                          # type: ignore[attr-defined]
        or (sale.customer.name if sale.customer else None)  # type: ignore[attr-defined]
    )
    if customer_name:
        lines.append(f"Customer: {customer_name}")

    lines.append("")
    lines.append("*Items:*")
    for item in sale.items:                                 # type: ignore[attr-defined]
        lines.append(
            f"  • #{item.item_id}  ×{item.quantity}  "
            f"@{_fmt(item.unit_price)}  =  {_fmt(item.total_price)}"
        )

    lines.append("")
    lines.append(f"Subtotal:  {_fmt(sale.subtotal)}")      # type: ignore[attr-defined]
    if Decimal(str(sale.discount)) > 0:                    # type: ignore[attr-defined]
        lines.append(f"Discount:  -{_fmt(sale.discount)}") # type: ignore[attr-defined]
    if Decimal(str(sale.tax)) > 0:                         # type: ignore[attr-defined]
        lines.append(f"Tax:       +{_fmt(sale.tax)}")      # type: ignore[attr-defined]
    lines.append(f"*Total:    {_fmt(sale.total_amount)}*") # type: ignore[attr-defined]

    if Decimal(str(sale.paid_amount)) > 0:                 # type: ignore[attr-defined]
        lines.append(f"Paid:      {_fmt(sale.paid_amount)}")  # type: ignore[attr-defined]
    if Decimal(str(sale.due_amount)) > 0:                  # type: ignore[attr-defined]
        lines.append(f"*Due:      {_fmt(sale.due_amount)}*")  # type: ignore[attr-defined]

    if sale.notes:                                         # type: ignore[attr-defined]
        lines.append("")
        lines.append(f"Notes: {sale.notes}")               # type: ignore[attr-defined]

    return "\n".join(lines)


async def send_receipt(phone: str, message: str) -> str:
    """Send a text message via WhatsApp Business Cloud API. Returns the message ID."""
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        raise RuntimeError(
            "WhatsApp is not configured. Set WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_PHONE_NUMBER_ID in .env"
        )

    url = f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        detail = response.json().get("error", {}).get("message", response.text)
        raise RuntimeError(f"WhatsApp API error: {detail}")

    data = response.json()
    return data["messages"][0]["id"]
