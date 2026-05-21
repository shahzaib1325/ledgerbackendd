import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def inspect():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id, order_no, status, start_date, end_date, total_cost, total_labor_cost, total_other_cost FROM production_orders"))
        print("=== Production Orders ===")
        for row in res.mappings().all():
            print(dict(row))

if __name__ == '__main__':
    asyncio.run(inspect())
