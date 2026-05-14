"""
Business logic for the Reports module.

All functions are read-only aggregations — no mutations.
Uses raw SQL (text()) for complex aggregations that span multiple tables
and benefit from a single DB round-trip over ORM composition.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.reports import (
    AccountCashFlowRow,
    CashFlowReport,
    CustomerBalanceReport,
    CustomerBalanceRow,
    CustomerSalesRow,
    PayrollSummaryReport,
    PayrollSummaryRow,
    ProductionSummaryReport,
    ProductionSummaryRow,
    ProfitLossReport,
    PurchaseSummaryReport,
    StockMovementReport,
    StockMovementRow,
    StockSummaryReport,
    StockSummaryRow,
    SupplierBalanceReport,
    SupplierBalanceRow,
    SupplierPurchaseRow,
    SalesSummaryReport,
)


# ── Profit & Loss ─────────────────────────────────────────────────────────────

async def profit_loss(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> ProfitLossReport:
    # Revenue: confirmed/paid/partially_paid sales minus approved returns in range
    rev = await db.execute(text("""
        SELECT COALESCE(SUM(total_amount), 0) AS revenue
        FROM sale_invoices
        WHERE invoice_date BETWEEN :from AND :to
          AND status NOT IN ('draft', 'void')
    """), {"from": date_from, "to": date_to})
    gross_revenue = Decimal(str(rev.scalar_one()))

    ret = await db.execute(text("""
        SELECT COALESCE(SUM(sr.total_amount), 0) AS returns
        FROM sale_returns sr
        JOIN sale_invoices si ON si.id = sr.invoice_id
        WHERE si.invoice_date BETWEEN :from AND :to
          AND si.status NOT IN ('draft', 'void')
          AND sr.status = 'approved'
    """), {"from": date_from, "to": date_to})
    total_returns = Decimal(str(ret.scalar_one()))

    total_revenue = gross_revenue - total_returns

    # Purchase cost: confirmed purchases in range
    pur = await db.execute(text("""
        SELECT COALESCE(SUM(total_amount), 0) AS cost
        FROM purchases
        WHERE purchase_date BETWEEN :from AND :to
          AND status NOT IN ('draft', 'void')
    """), {"from": date_from, "to": date_to})
    total_purchase_cost = Decimal(str(pur.scalar_one()))

    gross_profit = total_revenue - total_purchase_cost

    # Salary expense in range (paid_at)
    sal = await db.execute(text("""
        SELECT COALESCE(SUM(net_salary), 0) AS expense
        FROM staff_payments
        WHERE paid_at::date BETWEEN :from AND :to
    """), {"from": date_from, "to": date_to})
    total_salary_expense = Decimal(str(sal.scalar_one()))

    # Advance expense in range
    adv = await db.execute(text("""
        SELECT COALESCE(SUM(amount), 0) AS expense
        FROM advances
        WHERE paid_at::date BETWEEN :from AND :to
    """), {"from": date_from, "to": date_to})
    total_advance_expense = Decimal(str(adv.scalar_one()))

    # Production labor costs in range (from completed orders)
    labor = await db.execute(text("""
        SELECT COALESCE(SUM(pl.total_cost), 0) AS expense
        FROM production_labor pl
        JOIN production_orders po ON po.id = pl.order_id
        WHERE po.status = 'completed'
          AND po.end_date BETWEEN :from AND :to
    """), {"from": date_from, "to": date_to})
    total_production_labor_expense = Decimal(str(labor.scalar_one()))

    # Production other costs in range (from completed orders)
    prod = await db.execute(text("""
        SELECT COALESCE(SUM(pc.amount), 0) AS expense
        FROM production_costs pc
        JOIN production_orders po ON po.id = pc.order_id
        WHERE po.status = 'completed'
          AND po.end_date BETWEEN :from AND :to
    """), {"from": date_from, "to": date_to})
    total_other_expense = Decimal(str(prod.scalar_one()))

    net_profit = (
        gross_profit
        - total_salary_expense
        - total_advance_expense
        - total_production_labor_expense
        - total_other_expense
    )

    return ProfitLossReport(
        date_from=date_from,
        date_to=date_to,
        total_revenue=total_revenue,
        total_purchase_cost=total_purchase_cost,
        gross_profit=gross_profit,
        total_salary_expense=total_salary_expense,
        total_advance_expense=total_advance_expense,
        total_production_labor_expense=total_production_labor_expense,
        total_other_expense=total_other_expense,
        net_profit=net_profit,
    )


# ── Sales Summary ─────────────────────────────────────────────────────────────

async def sales_summary(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> SalesSummaryReport:
    # Header totals
    hdr = await db.execute(text("""
        SELECT
            COALESCE(SUM(total_amount), 0)  AS invoiced,
            COALESCE(SUM(paid_amount), 0)   AS collected,
            COALESCE(SUM(due_amount), 0)    AS outstanding,
            COUNT(*)                         AS cnt
        FROM sale_invoices
        WHERE invoice_date BETWEEN :from AND :to
          AND status NOT IN ('draft', 'void')
    """), {"from": date_from, "to": date_to})
    row = hdr.mappings().one()

    # Per-customer breakdown
    detail = await db.execute(text("""
        SELECT
            si.customer_id,
            c.name                                AS customer_name,
            COUNT(si.id)                          AS invoice_count,
            COALESCE(SUM(si.total_amount), 0)     AS total_invoiced,
            COALESCE(SUM(si.paid_amount), 0)      AS total_collected,
            COALESCE(SUM(si.due_amount), 0)       AS total_outstanding
        FROM sale_invoices si
        JOIN customers c ON c.id = si.customer_id
        WHERE si.invoice_date BETWEEN :from AND :to
          AND si.status NOT IN ('draft', 'void')
        GROUP BY si.customer_id, c.name
        ORDER BY total_invoiced DESC
    """), {"from": date_from, "to": date_to})

    return SalesSummaryReport(
        date_from=date_from,
        date_to=date_to,
        total_invoiced=Decimal(str(row["invoiced"])),
        total_collected=Decimal(str(row["collected"])),
        total_outstanding=Decimal(str(row["outstanding"])),
        invoice_count=int(row["cnt"]),
        customer_breakdown=[
            CustomerSalesRow(
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                invoice_count=int(r["invoice_count"]),
                total_invoiced=Decimal(str(r["total_invoiced"])),
                total_collected=Decimal(str(r["total_collected"])),
                total_outstanding=Decimal(str(r["total_outstanding"])),
            )
            for r in detail.mappings().all()
        ],
    )


# ── Purchase Summary ──────────────────────────────────────────────────────────

async def purchase_summary(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> PurchaseSummaryReport:
    hdr = await db.execute(text("""
        SELECT
            COALESCE(SUM(total_amount), 0)  AS purchased,
            COALESCE(SUM(paid_amount), 0)   AS paid,
            COALESCE(SUM(due_amount), 0)    AS outstanding,
            COUNT(*)                         AS cnt
        FROM purchases
        WHERE purchase_date BETWEEN :from AND :to
          AND status NOT IN ('draft', 'void')
    """), {"from": date_from, "to": date_to})
    row = hdr.mappings().one()

    detail = await db.execute(text("""
        SELECT
            p.supplier_id,
            s.name                               AS supplier_name,
            COUNT(p.id)                          AS order_count,
            COALESCE(SUM(p.total_amount), 0)     AS total_purchased,
            COALESCE(SUM(p.paid_amount), 0)      AS total_paid,
            COALESCE(SUM(p.due_amount), 0)       AS total_outstanding
        FROM purchases p
        JOIN suppliers s ON s.id = p.supplier_id
        WHERE p.purchase_date BETWEEN :from AND :to
          AND p.status NOT IN ('draft', 'void')
        GROUP BY p.supplier_id, s.name
        ORDER BY total_purchased DESC
    """), {"from": date_from, "to": date_to})

    from app.schemas.reports import PurchaseSummaryReport
    return PurchaseSummaryReport(
        date_from=date_from,
        date_to=date_to,
        total_purchased=Decimal(str(row["purchased"])),
        total_paid=Decimal(str(row["paid"])),
        total_outstanding=Decimal(str(row["outstanding"])),
        order_count=int(row["cnt"]),
        supplier_breakdown=[
            SupplierPurchaseRow(
                supplier_id=r["supplier_id"],
                supplier_name=r["supplier_name"],
                order_count=int(r["order_count"]),
                total_purchased=Decimal(str(r["total_purchased"])),
                total_paid=Decimal(str(r["total_paid"])),
                total_outstanding=Decimal(str(r["total_outstanding"])),
            )
            for r in detail.mappings().all()
        ],
    )


# ── Stock Summary ─────────────────────────────────────────────────────────────

async def stock_summary(
    db: AsyncSession,
    category_id: int | None = None,
    below_reorder_only: bool = False,
) -> StockSummaryReport:
    filters = []
    params: dict = {}
    if category_id is not None:
        filters.append("i.category_id = :cat_id")
        params["cat_id"] = category_id
    if below_reorder_only:
        filters.append("i.reorder_level > 0 AND i.current_stock <= i.reorder_level")

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    rows = await db.execute(text(f"""
        SELECT
            i.id            AS item_id,
            i.name          AS item_name,
            i.sku,
            i.category_id,
            c.name          AS category_name,
            i.current_stock,
            i.reorder_level,
            (i.current_stock <= i.reorder_level) AS is_below_reorder
        FROM items i
        LEFT JOIN categories c ON c.id = i.category_id
        {where}
        ORDER BY i.name
    """), params)

    items = [
        StockSummaryRow(
            item_id=r["item_id"],
            item_name=r["item_name"],
            sku=r["sku"],
            category_id=r["category_id"],
            category_name=r["category_name"],
            current_stock=Decimal(str(r["current_stock"])),
            reorder_level=Decimal(str(r["reorder_level"])),
            is_below_reorder=bool(r["is_below_reorder"]),
        )
        for r in rows.mappings().all()
    ]

    return StockSummaryReport(
        generated_at=datetime.now(timezone.utc),
        items=items,
        total_items=len(items),
        below_reorder_count=sum(1 for i in items if i.is_below_reorder),
    )


# ── Stock Movement ────────────────────────────────────────────────────────────

async def stock_movements(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    *,
    item_id: int | None = None,
    movement_type: str | None = None,
    page: int = 1,
    limit: int = 50,
) -> StockMovementReport:
    filters = ["sm.moved_at::date BETWEEN :from AND :to"]
    params: dict = {"from": date_from, "to": date_to}

    if item_id is not None:
        filters.append("sm.item_id = :item_id")
        params["item_id"] = item_id
    if movement_type is not None:
        if movement_type == "in":
            filters.append("sm.movement_type IN ('purchase_in', 'production_in', 'return_in')")
        elif movement_type == "out":
            filters.append("sm.movement_type IN ('sale_out', 'production_out', 'return_out')")
        else:
            filters.append("sm.movement_type = :mvt_type")
            params["mvt_type"] = movement_type

    where = "WHERE " + " AND ".join(filters)
    offset = (page - 1) * limit
    params["limit"] = limit
    params["offset"] = offset

    cnt = await db.execute(text(f"""
        SELECT COUNT(*) FROM stock_movements sm {where}
    """), params)
    total = int(cnt.scalar_one())

    rows = await db.execute(text(f"""
        SELECT
            sm.id           AS movement_id,
            sm.item_id,
            i.name          AS item_name,
            sm.movement_type,
            sm.quantity,
            sm.stock_after,
            sm.reference_id,
            sm.moved_at::date AS movement_date,
            sm.moved_at
        FROM stock_movements sm
        JOIN items i ON i.id = sm.item_id
        {where}
        ORDER BY sm.moved_at DESC
        LIMIT :limit OFFSET :offset
    """), params)

    return StockMovementReport(
        date_from=date_from,
        date_to=date_to,
        item_id=item_id,
        rows=[
            StockMovementRow(
                movement_id=r["movement_id"],
                item_id=r["item_id"],
                item_name=r["item_name"],
                movement_type=r["movement_type"],
                quantity=Decimal(str(r["quantity"])),
                stock_after=Decimal(str(r["stock_after"])),
                reference_id=r["reference_id"],
                movement_date=r["movement_date"],
                created_at=r["moved_at"],
            )
            for r in rows.mappings().all()
        ],
        total=total,
    )


# ── Customer Balances ─────────────────────────────────────────────────────────

async def customer_balances(
    db: AsyncSession,
    *,
    balance_type: str | None = None,
    min_balance: Decimal | None = None,
) -> CustomerBalanceReport:
    filters = ["c.is_active = true"]
    params: dict = {}
    if balance_type is not None:
        filters.append("c.balance_type = :bt")
        params["bt"] = balance_type
    if min_balance is not None:
        filters.append("c.balance >= :min_bal")
        params["min_bal"] = min_balance

    where = "WHERE " + " AND ".join(filters)

    rows = await db.execute(text(f"""
        SELECT id, name, phone, balance, balance_type, credit_limit
        FROM customers c
        {where}
        ORDER BY balance DESC
    """), params)

    customers = [
        CustomerBalanceRow(
            customer_id=r["id"],
            customer_name=r["name"],
            phone=r["phone"],
            balance=Decimal(str(r["balance"])),
            balance_type=r["balance_type"],
            credit_limit=Decimal(str(r["credit_limit"])),
        )
        for r in rows.mappings().all()
    ]

    total_receivable = sum(
        c.balance for c in customers if c.balance_type.value == "receivable"
    )
    total_payable = sum(
        c.balance for c in customers if c.balance_type.value == "payable"
    )

    return CustomerBalanceReport(
        generated_at=datetime.now(timezone.utc),
        customers=customers,
        total_receivable=total_receivable,
        total_payable=total_payable,
    )


# ── Supplier Balances ─────────────────────────────────────────────────────────

async def supplier_balances(
    db: AsyncSession,
    *,
    balance_type: str | None = None,
) -> SupplierBalanceReport:
    filters = ["s.is_active = true"]
    params: dict = {}
    if balance_type is not None:
        filters.append("s.balance_type = :bt")
        params["bt"] = balance_type

    where = "WHERE " + " AND ".join(filters)

    rows = await db.execute(text(f"""
        SELECT id, name, phone, balance, balance_type
        FROM suppliers s
        {where}
        ORDER BY balance DESC
    """), params)

    suppliers = [
        SupplierBalanceRow(
            supplier_id=r["id"],
            supplier_name=r["name"],
            phone=r["phone"],
            balance=Decimal(str(r["balance"])),
            balance_type=r["balance_type"],
        )
        for r in rows.mappings().all()
    ]

    total_payable = sum(
        s.balance for s in suppliers if s.balance_type.value == "payable"
    )
    total_receivable = sum(
        s.balance for s in suppliers if s.balance_type.value == "receivable"
    )

    return SupplierBalanceReport(
        generated_at=datetime.now(timezone.utc),
        suppliers=suppliers,
        total_payable=total_payable,
        total_receivable=total_receivable,
    )


# ── Cash Flow ─────────────────────────────────────────────────────────────────

async def cash_flow(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> CashFlowReport:
    rows = await db.execute(text("""
        SELECT
            a.id                                                        AS account_id,
            a.name                                                      AS account_name,
            a.account_type,
            a.opening_balance,
            a.current_balance,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'credit'
                         THEN t.amount ELSE 0 END), 0)                 AS total_credits,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'debit'
                         THEN t.amount ELSE 0 END), 0)                 AS total_debits
        FROM accounts a
        LEFT JOIN transactions t
            ON t.account_id = a.id
            AND t.transaction_date BETWEEN :from AND :to
        WHERE a.is_active = true
        GROUP BY a.id, a.name, a.account_type, a.opening_balance, a.current_balance
        ORDER BY a.name
    """), {"from": date_from, "to": date_to})

    accounts = []
    net_cash_in = Decimal("0")
    net_cash_out = Decimal("0")

    for r in rows.mappings().all():
        credits = Decimal(str(r["total_credits"]))
        debits = Decimal(str(r["total_debits"]))
        net_cash_in += credits
        net_cash_out += debits
        accounts.append(AccountCashFlowRow(
            account_id=r["account_id"],
            account_name=r["account_name"],
            account_type=r["account_type"],
            opening_balance=Decimal(str(r["opening_balance"])),
            total_credits=credits,
            total_debits=debits,
            closing_balance=Decimal(str(r["current_balance"])),
        ))

    return CashFlowReport(
        date_from=date_from,
        date_to=date_to,
        accounts=accounts,
        net_cash_in=net_cash_in,
        net_cash_out=net_cash_out,
        net_position=net_cash_in - net_cash_out,
    )


# ── Payroll Summary ───────────────────────────────────────────────────────────

async def payroll_summary(
    db: AsyncSession,
    payment_month: int,
    payment_year: int,
) -> PayrollSummaryReport:
    rows = await db.execute(text("""
        SELECT
            sp.staff_id,
            s.name          AS staff_name,
            s.staff_type,
            sp.payment_month,
            sp.payment_year,
            sp.gross_salary,
            sp.total_allowances,
            sp.total_deductions,
            sp.advance_deduction,
            sp.net_salary
        FROM staff_payments sp
        JOIN staff s ON s.id = sp.staff_id
        WHERE sp.payment_month = :month AND sp.payment_year = :year
        ORDER BY s.name
    """), {"month": payment_month, "year": payment_year})

    payment_rows = [
        PayrollSummaryRow(
            staff_id=r["staff_id"],
            staff_name=r["staff_name"],
            staff_type=r["staff_type"],
            payment_month=r["payment_month"],
            payment_year=r["payment_year"],
            gross_salary=Decimal(str(r["gross_salary"])),
            total_allowances=Decimal(str(r["total_allowances"])),
            total_deductions=Decimal(str(r["total_deductions"])),
            advance_deduction=Decimal(str(r["advance_deduction"])),
            net_salary=Decimal(str(r["net_salary"])),
        )
        for r in rows.mappings().all()
    ]

    return PayrollSummaryReport(
        payment_month=payment_month,
        payment_year=payment_year,
        rows=payment_rows,
        total_gross=sum(r.gross_salary for r in payment_rows),
        total_net=sum(r.net_salary for r in payment_rows),
        total_staff_paid=len(payment_rows),
    )


# ── Production Summary ────────────────────────────────────────────────────────

async def production_summary(
    db: AsyncSession,
    date_from: date,
    date_to: date,
) -> ProductionSummaryReport:
    rows = await db.execute(text("""
        SELECT
            po.id               AS order_id,
            po.order_no,
            po.product_item_id,
            i.name              AS product_item_name,
            po.quantity_to_produce,
            COALESCE(SUM(out.quantity_produced), 0) AS quantity_produced,
            po.status,
            po.total_cost,
            po.start_date,
            po.end_date
        FROM production_orders po
        JOIN items i ON i.id = po.product_item_id
        LEFT JOIN production_output out ON out.order_id = po.id
        WHERE po.created_at::date BETWEEN :from AND :to
        GROUP BY po.id, i.name
        ORDER BY po.created_at DESC
    """), {"from": date_from, "to": date_to})

    prod_rows = [
        ProductionSummaryRow(
            order_id=r["order_id"],
            order_no=r["order_no"],
            product_item_id=r["product_item_id"],
            product_item_name=r["product_item_name"],
            quantity_to_produce=Decimal(str(r["quantity_to_produce"])),
            quantity_produced=Decimal(str(r["quantity_produced"])),
            status=r["status"],
            total_cost=Decimal(str(r["total_cost"])),
            start_date=r["start_date"],
            end_date=r["end_date"],
        )
        for r in rows.mappings().all()
    ]

    return ProductionSummaryReport(
        date_from=date_from,
        date_to=date_to,
        rows=prod_rows,
        total_orders=len(prod_rows),
        completed_orders=sum(1 for r in prod_rows if r.status.value == "completed"),
        total_production_cost=sum(r.total_cost for r in prod_rows),
    )
