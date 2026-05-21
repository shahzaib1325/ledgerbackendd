import asyncio
from app.core.database import AsyncSessionLocal
from app.services.dashboard_service import get_dashboard

async def main():
    async with AsyncSessionLocal() as db:
        data = await get_dashboard(db)
        print("=== DASHBOARD VALIDATION ===")
        print("Dashboard Overdue items returned count:", len(data.overdue_sales))
        for o in data.overdue_sales:
            print(f"  - Sale Invoice ID {o.id}: {o.invoice_no} (Due Date: {o.due_date}, Due Amount: {o.due_amount})")

if __name__ == '__main__':
    asyncio.run(main())
