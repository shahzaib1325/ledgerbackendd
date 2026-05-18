"""
Global search — queries across customers, suppliers, staff, inventory, sales, and purchases.
Returns a unified list of results grouped by entity type.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.search import SearchResponse, SearchResultItem


async def global_search(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 20,
) -> SearchResponse:
    if not query or len(query.strip()) < 1:
        return SearchResponse(query=query, results=[], total=0)

    q = f"%{query.strip()}%"
    results: list[SearchResultItem] = []

    # ── Customers ─────────────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT id, name, phone, balance, balance_type, credit_limit, is_active
        FROM customers
        WHERE name ILIKE :q OR phone ILIKE :q OR email ILIKE :q
        ORDER BY name
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="customer",
            id=r["id"],
            name=r["name"],
            subtitle=r["phone"] or None,
            meta={
                "balance": str(r["balance"]),
                "balance_type": r["balance_type"],
                "credit_limit": str(r["credit_limit"]),
                "is_active": r["is_active"],
            },
            href=f"/customers/{r['id']}",
        ))

    # ── Suppliers ─────────────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT id, name, phone, balance, balance_type, is_active
        FROM suppliers
        WHERE name ILIKE :q OR phone ILIKE :q OR email ILIKE :q
        ORDER BY name
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="supplier",
            id=r["id"],
            name=r["name"],
            subtitle=r["phone"] or None,
            meta={
                "balance": str(r["balance"]),
                "balance_type": r["balance_type"],
                "is_active": r["is_active"],
            },
            href=f"/suppliers/{r['id']}",
        ))

    # ── Staff ─────────────────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT id, name, phone, department, designation, compensation_type, is_active
        FROM staff
        WHERE name ILIKE :q OR phone ILIKE :q OR cnic ILIKE :q
        ORDER BY name
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="staff",
            id=r["id"],
            name=r["name"],
            subtitle=r["department"] or r["designation"] or None,
            meta={
                "compensation_type": r["compensation_type"],
                "is_active": r["is_active"],
            },
            href=f"/staff/{r['id']}",
        ))

    # ── Inventory Items ───────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT id, name, sku, item_type, current_stock, sale_price, is_active
        FROM items
        WHERE name ILIKE :q OR sku ILIKE :q
        ORDER BY name
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="item",
            id=r["id"],
            name=r["name"],
            subtitle=r["sku"] or None,
            meta={
                "item_type": r["item_type"],
                "current_stock": str(r["current_stock"]),
                "sale_price": str(r["sale_price"]),
                "is_active": r["is_active"],
            },
            href=f"/inventory/{r['id']}",
        ))

    # ── Sales ─────────────────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT si.id, si.invoice_no, si.total_amount, si.status, si.invoice_date,
               COALESCE(c.name, si.walking_customer_name, 'Walk-in') AS customer_name
        FROM sale_invoices si
        LEFT JOIN customers c ON c.id = si.customer_id
        WHERE si.invoice_no ILIKE :q OR COALESCE(c.name, si.walking_customer_name, '') ILIKE :q
        ORDER BY si.invoice_date DESC
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="sale",
            id=r["id"],
            name=r["invoice_no"] or f"INV #{r['id']}",
            subtitle=r["customer_name"],
            meta={
                "total_amount": str(r["total_amount"]),
                "status": r["status"],
                "date": str(r["invoice_date"]),
            },
            href=f"/sales/{r['id']}",
        ))

    # ── Purchases ─────────────────────────────────────────────────────────
    rows = await db.execute(text("""
        SELECT p.id, p.invoice_no, p.total_amount, p.status, p.purchase_date,
               s.name AS supplier_name
        FROM purchases p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.invoice_no ILIKE :q OR s.name ILIKE :q
        ORDER BY p.purchase_date DESC
        LIMIT :lim
    """), {"q": q, "lim": limit})
    for r in rows.mappings().all():
        results.append(SearchResultItem(
            entity_type="purchase",
            id=r["id"],
            name=r["invoice_no"] or f"PO #{r['id']}",
            subtitle=r["supplier_name"],
            meta={
                "total_amount": str(r["total_amount"]),
                "status": r["status"],
                "date": str(r["purchase_date"]),
            },
            href=f"/purchases/{r['id']}",
        ))

    return SearchResponse(
        query=query,
        results=results[:limit],
        total=len(results),
    )
