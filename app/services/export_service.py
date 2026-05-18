"""
Export service for the Reports module.

Generates CSV, XLSX, and PDF files from report data synchronously.
Report name → service function whitelist prevents arbitrary code execution.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services import report_service

# Whitelist: report_name → callable that accepts (db, **params) → report object
_REPORT_REGISTRY: dict[str, Any] = {
    "profit-loss": report_service.profit_loss,
    "sales-summary": report_service.sales_summary,
    "purchase-summary": report_service.purchase_summary,
    "stock-summary": report_service.stock_summary,
    "stock-movements": report_service.stock_movements,
    "customer-balances": report_service.customer_balances,
    "supplier-balances": report_service.supplier_balances,
    "cash-flow": report_service.cash_flow,
    "payroll-summary": report_service.payroll_summary,
    "production-summary": report_service.production_summary,
    "activity-ledger": report_service.activity_ledger,
}


def get_report_fn(report_name: str) -> Any | None:
    return _REPORT_REGISTRY.get(report_name)


def rows_to_csv_bytes(rows: list[dict]) -> bytes:
    import csv
    import io

    buf = io.StringIO()
    if not rows:
        return b""
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def rows_to_xlsx_bytes(rows: list[dict]) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    if not rows:
        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([str(v) if isinstance(v, Decimal) else v for v in row.values()])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def rows_to_pdf_bytes(rows: list[dict], title: str = "Report") -> bytes:
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()

    if not rows:
        doc = SimpleDocTemplate(buf, pagesize=A4)
        styles = getSampleStyleSheet()
        doc.build([Paragraph(title, styles["Title"]), Spacer(1, 12), Paragraph("No data available.")])
        return buf.getvalue()

    headers = list(rows[0].keys())

    # Use landscape if many columns
    page_size = landscape(A4) if len(headers) > 6 else A4

    doc = SimpleDocTemplate(
        buf, pagesize=page_size,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 8))

    # Clean header labels
    clean_headers = [h.replace("_", " ").title() for h in headers]

    # Build table data
    table_data = [clean_headers]
    for row in rows:
        table_data.append([str(v) if v is not None else "" for v in row.values()])

    # Calculate column widths proportionally
    avail_width = page_size[0] - 20 * mm
    col_width = avail_width / len(headers)
    col_widths = [col_width] * len(headers)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        f"Total rows: {len(rows)}",
        styles["Normal"],
    ))

    doc.build(elements)
    return buf.getvalue()


def report_to_rows(report_obj: Any) -> list[dict]:
    """Flatten a report schema object into a list of dicts for export."""
    # Activity ledger: flatten nested entities → activities into one row per activity
    entities = getattr(report_obj, "entities", None)
    if entities is not None and len(entities) > 0 and hasattr(entities[0], "activities"):
        flat_rows = []
        for entity in entities:
            for act in entity.activities:
                flat_rows.append({
                    "entity_type": entity.entity_type,
                    "entity_name": entity.entity_name,
                    "phone": entity.phone or "",
                    "date": act.date,
                    "activity_type": act.activity_type,
                    "reference": act.reference,
                    "description": act.description,
                    "amount": str(act.amount) if act.amount is not None else "",
                })
        return flat_rows

    # Reports with a primary row list
    for attr in ("rows", "items", "customers", "suppliers", "accounts"):
        collection = getattr(report_obj, attr, None)
        if collection is not None:
            return [_model_to_dict(r) for r in collection]
    # Flat reports (e.g. ProfitLossReport)
    return [_model_to_dict(report_obj)]


def _model_to_dict(obj: Any) -> dict:
    if hasattr(obj, "model_dump"):
        return {k: str(v) if isinstance(v, Decimal) else v
                for k, v in obj.model_dump().items()}
    return dict(obj)
