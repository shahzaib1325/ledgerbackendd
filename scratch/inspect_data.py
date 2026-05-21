import asyncio
from datetime import date
from app.core.database import AsyncSessionLocal
from app.services.report_service import cash_flow
from app.models.transaction import Account
from sqlalchemy import select

async def inspect():
    async with AsyncSessionLocal() as db:
        # count accounts
        acc_res = await db.execute(select(Account))
        accounts = acc_res.scalars().all()
        print('Accounts count:', len(accounts))
        for a in accounts:
            print(f'Account {a.id}: {a.name}, active={a.is_active}')
        # count transactions
        tx_res = await db.execute(select("transactions"))
        # using raw SQL to count
        tx_count = await db.execute("SELECT COUNT(*) FROM transactions")
        print('Transactions count:', tx_count.scalar_one())
        # run cash flow for a wide range
        cf_report = await cash_flow(db, date(2020,1,1), date(2030,12,31))
        print('Cash flow accounts returned:', len(cf_report.accounts))
        for row in cf_report.accounts:
            print(row.account_id, row.account_name, row.total_credits, row.total_debits)

if __name__ == '__main__':
    asyncio.run(inspect())
