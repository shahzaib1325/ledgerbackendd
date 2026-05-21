import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id, invoice_no, due_date, invoice_date, status, due_amount FROM sale_invoices"))
        for row in res.mappings().all():
            print(dict(row))

if __name__ == '__main__':
    asyncio.run(main())
