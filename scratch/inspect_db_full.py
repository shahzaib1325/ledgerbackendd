import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def inspect():
    async with AsyncSessionLocal() as db:
        print("=== Tables Inspection ===")
        tables = [
            "users", "customers", "suppliers", "items", "categories",
            "purchases", "purchase_items", "sale_invoices", "sale_items",
            "sale_returns", "staff", "staff_payments", "advances",
            "production_orders", "production_labor", "production_costs",
            "accounts", "transactions", "transfers"
        ]
        
        for table in tables:
            try:
                res = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = res.scalar_one()
                print(f"Table '{table}': {count} rows")
            except Exception as e:
                print(f"Table '{table}' error: {e}")

        # Let's inspect accounts
        print("\n=== Accounts ===")
        try:
            res = await db.execute(text("SELECT * FROM accounts"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Accounts select error:", e)

        # Let's inspect Transactions
        print("\n=== Transactions (Top 20) ===")
        try:
            res = await db.execute(text("SELECT * FROM transactions ORDER BY id DESC LIMIT 20"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Transactions select error:", e)

        # Let's inspect sales
        print("\n=== Sales (Top 20) ===")
        try:
            res = await db.execute(text("SELECT * FROM sale_invoices ORDER BY id DESC LIMIT 20"))
            for row in res.mappings().all():
                # print a clean dict with selected fields
                d = dict(row)
                keys_to_print = ["id", "invoice_no", "customer_id", "total_amount", "paid_amount", "due_amount", "status", "invoice_date"]
                print({k: d.get(k) for k in keys_to_print if k in d})
        except Exception as e:
            print("Sales select error:", e)

        # Let's inspect purchases
        print("\n=== Purchases (Top 20) ===")
        try:
            res = await db.execute(text("SELECT * FROM purchases ORDER BY id DESC LIMIT 20"))
            for row in res.mappings().all():
                d = dict(row)
                keys_to_print = ["id", "purchase_no", "supplier_id", "total_amount", "paid_amount", "due_amount", "status", "purchase_date", "invoice_no"]
                print({k: d.get(k) for k in keys_to_print if k in d})
        except Exception as e:
            print("Purchases select error:", e)

        # Let's inspect staff payments and advances
        print("\n=== Staff Payments ===")
        try:
            res = await db.execute(text("SELECT * FROM staff_payments"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Staff payments error:", e)

        print("\n=== Advances ===")
        try:
            res = await db.execute(text("SELECT * FROM advances"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Advances error:", e)

        print("\n=== Production Labor and Costs ===")
        try:
            res = await db.execute(text("SELECT * FROM production_labor"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Production labor error:", e)
            
        try:
            res = await db.execute(text("SELECT * FROM production_costs"))
            for row in res.mappings().all():
                print(dict(row))
        except Exception as e:
            print("Production costs error:", e)

if __name__ == '__main__':
    asyncio.run(inspect())
