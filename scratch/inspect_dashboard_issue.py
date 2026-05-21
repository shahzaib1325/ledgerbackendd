import asyncio
from datetime import date
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.models.inventory import Item
from app.models.sale import SaleInvoice

async def inspect():
    async with AsyncSessionLocal() as db:
        # 1. Inspect Items
        print("=== ITEMS (INVENTORY) ===")
        total_items = await db.execute(text("SELECT COUNT(*) FROM items"))
        print(f"Total items in DB: {total_items.scalar_one()}")
        
        below_reorder = await db.execute(text(
            "SELECT COUNT(*) FROM items WHERE reorder_level > 0 AND current_stock <= reorder_level"
        ))
        print(f"Items below reorder level (low stock query): {below_reorder.scalar_one()}")
        
        all_items_with_reorder = await db.execute(text(
            "SELECT id, name, current_stock, reorder_level FROM items LIMIT 10"
        ))
        print("Sample items in DB:")
        for row in all_items_with_reorder.mappings().all():
            print(f"  - Item ID {row['id']}: {row['name']} (Stock: {row['current_stock']}, Reorder Level: {row['reorder_level']})")
        
        # 2. Inspect Overdue Sale Invoices
        print("\n=== OVERDUE SALES ===")
        today = date.today()
        print(f"Today is: {today}")
        
        overdue_cnt = await db.execute(text(
            "SELECT COUNT(*) FROM sale_invoices WHERE due_date <= :today AND due_amount > 0 AND status NOT IN ('void', 'returned')"
        ), {"today": today})
        print(f"Overdue sales count (dashboard query logic): {overdue_cnt.scalar_one()}")
        
        all_sales = await db.execute(text(
            "SELECT id, invoice_no, due_date, due_amount, status FROM sale_invoices LIMIT 10"
        ))
        print("Sample sales in DB:")
        for row in all_sales.mappings().all():
            print(f"  - Sale ID {row['id']}: {row['invoice_no']} (Due Date: {row['due_date']}, Due Amount: {row['due_amount']}, Status: {row['status']})")

if __name__ == "__main__":
    asyncio.run(inspect())
