import os
import json
import asyncio
import httpx

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')
LOGIN_URL = f"{BASE_URL}/api/v1/auth/login"
PAYROLL_URL = f"{BASE_URL}/api/v1/reports/payroll-summary"
CASHFLOW_URL = f"{BASE_URL}/api/v1/reports/cash-flow"

async def login(email: str, password: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(LOGIN_URL, json={"email": email, "password": password})
        resp.raise_for_status()
        data = resp.json()
        return data["data"]["access_token"]

async def get_payroll(token: str, month: int, year: int):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(PAYROLL_URL, params={"payment_month": month, "payment_year": year}, headers=headers)
        print("Payroll status:", resp.status_code)
        print(resp.text)

async def get_cashflow(token: str, date_from: str, date_to: str):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(CASHFLOW_URL, params={"date_from": date_from, "date_to": date_to}, headers=headers)
        print("Cash flow status:", resp.status_code)
        print(resp.text)

async def main():
    token = await login("admin@example.com", "AdminNewPass2!")
    await get_payroll(token, month=9, year=2023)
    await get_cashflow(token, date_from="2023-01-01", date_to="2023-12-31")

if __name__ == "__main__":
    asyncio.run(main())
