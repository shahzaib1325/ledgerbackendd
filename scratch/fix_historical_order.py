import asyncio
from datetime import date
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.services.report_service import profit_loss, cash_flow

async def main():
    async with AsyncSessionLocal() as db:
        # 1. Update the historical order's end_date
        print("=== Updating PRD-20260518-U7MD end_date to 2026-05-18 ===")
        await db.execute(text("""
            UPDATE production_orders 
            SET end_date = '2026-05-18' 
            WHERE order_no = 'PRD-20260518-U7MD'
        """))
        await db.commit()
        print("Update complete!\n")

        # 2. Run reports again
        d_from = date(2026, 5, 1)
        d_to = date(2026, 5, 31)
        
        pnl = await profit_loss(db, d_from, d_to)
        cf = await cash_flow(db, d_from, d_to)
        
        print("=== UPDATED PROFIT & LOSS REPORT ===")
        print("Total Revenue:", pnl.total_revenue)
        print("Total Purchase Cost:", pnl.total_purchase_cost)
        print("Gross Profit:", pnl.gross_profit)
        print("Total Salary Expense:", pnl.total_salary_expense)
        print("Total Production Labor Expense:", pnl.total_production_labor_expense)
        print("Total Other Expense:", pnl.total_other_expense)
        print("Net Profit:", pnl.net_profit)
        
        print("\n=== UPDATED CASH FLOW REPORT ===")
        print("Net Cash In:", cf.net_cash_in)
        print("Net Cash Out:", cf.net_cash_out)
        print("Net Position:", cf.net_position)

if __name__ == '__main__':
    asyncio.run(main())
