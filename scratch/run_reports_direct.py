import asyncio
from datetime import date
from decimal import Decimal
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.services.report_service import profit_loss, cash_flow

async def main():
    async with AsyncSessionLocal() as db:
        d_from = date(2026, 5, 1)
        d_to = date(2026, 5, 31)
        
        pnl = await profit_loss(db, d_from, d_to)
        cf = await cash_flow(db, d_from, d_to)
        
        print("=== PROFIT & LOSS REPORT ===")
        print("Date from:", pnl.date_from)
        print("Date to:", pnl.date_to)
        print("Total Revenue:", pnl.total_revenue)
        print("Total Purchase Cost:", pnl.total_purchase_cost)
        print("Gross Profit:", pnl.gross_profit)
        print("Total Salary Expense:", pnl.total_salary_expense)
        print("Total Advance Expense:", pnl.total_advance_expense)
        print("Total Production Labor Expense:", pnl.total_production_labor_expense)
        print("Total Other Expense:", pnl.total_other_expense)
        print("Net Profit:", pnl.net_profit)
        
        print("\n=== CASH FLOW REPORT ===")
        print("Date from:", cf.date_from)
        print("Date to:", cf.date_to)
        print("Net Cash In:", cf.net_cash_in)
        print("Net Cash Out:", cf.net_cash_out)
        print("Net Position:", cf.net_position)
        print("Accounts details:")
        for ac in cf.accounts:
            print(f" - Account: {ac.account_name} (ID: {ac.account_id}), type={ac.account_type}, Credits={ac.total_credits}, Debits={ac.total_debits}, Opening={ac.opening_balance}, Closing={ac.closing_balance}")

        print("\n=== ALL TRANSACTIONS IN RANGE ===")
        res = await db.execute(text("""
            SELECT id, account_id, payment_method, transaction_type, reference_type, reference_id, amount, transaction_date, description
            FROM transactions
            WHERE transaction_date BETWEEN :from AND :to
            ORDER BY id ASC
        """), {"from": d_from, "to": d_to})
        for row in res.mappings().all():
            print(dict(row))

if __name__ == '__main__':
    asyncio.run(main())
