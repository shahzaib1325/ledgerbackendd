import asyncio
from sqlalchemy import text
from app.core.database import async_engine


async def main():
    async with async_engine.connect() as c:
        q = [
            ("items: total", "SELECT count(*) FROM items"),
            ("items: reorder_level > 0", "SELECT count(*) FROM items WHERE reorder_level > 0"),
            ("items: reorder_level = 0 or null",
             "SELECT count(*) FROM items WHERE reorder_level IS NULL OR reorder_level = 0"),
            ("items: current_stock <= 0",
             "SELECT count(*) FROM items WHERE current_stock <= 0"),
            ("items: BELOW reorder (dashboard query)",
             "SELECT count(*) FROM items WHERE reorder_level > 0 AND current_stock <= reorder_level"),
            ("sale_invoices: total", "SELECT count(*) FROM sale_invoices"),
            ("sale_invoices: due_date NOT NULL",
             "SELECT count(*) FROM sale_invoices WHERE due_date IS NOT NULL"),
            ("sale_invoices: due_amount > 0",
             "SELECT count(*) FROM sale_invoices WHERE due_amount > 0"),
            ("sale_invoices: due_date <= today",
             "SELECT count(*) FROM sale_invoices WHERE due_date <= CURRENT_DATE"),
            ("sale_invoices: OVERDUE (dashboard query)",
             "SELECT count(*) FROM sale_invoices "
             "WHERE due_date <= CURRENT_DATE AND due_amount > 0 "
             "AND status NOT IN ('void','returned')"),
        ]
        for label, sql in q:
            r = await c.execute(text(sql))
            print(f"{label:42s} -> {r.scalar()}")

        print("\nsale_invoices status breakdown:")
        r = await c.execute(text("SELECT status, count(*) FROM sale_invoices GROUP BY status"))
        for row in r.fetchall():
            print(f"  {row[0]:15s} {row[1]}")

        print("\nitems sample (name, current_stock, reorder_level):")
        r = await c.execute(text(
            "SELECT name, current_stock, reorder_level FROM items ORDER BY id LIMIT 10"))
        for row in r.fetchall():
            print(f"  {str(row[0])[:30]:30s} stock={row[1]}  reorder={row[2]}")


asyncio.run(main())
