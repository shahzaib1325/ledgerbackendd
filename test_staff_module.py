import asyncio
import httpx
from datetime import datetime, date

BASE_URL = "http://127.0.0.1:8000/api/v1/"

async def validate_staff_module():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("=== 0. Login ===")
        # Usually testadmin_final / Password123! from previous script works
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} - {resp.text}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print("\n=== 1. Create Staff ===")
        timestamp = int(datetime.now().timestamp())
        staff_payload = {
            "name": f"Test Staff {timestamp}",
            "phone": "1234567890",
            "cnic": f"12345-{timestamp}",
            "join_date": str(date.today()),
            "staff_type": "permanent",
            "department": "Engineering"
        }
        resp = await client.post("staff", json=staff_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Create staff failed: {resp.status_code} - {resp.text}")
            return
        staff_data = resp.json()["data"]
        staff_id = staff_data["id"]
        print(f"Staff created successfully: ID {staff_id}")

        print("\n=== 2. Add Salary Structure ===")
        salary_payload = {
            "basic_salary": 50000.0,
            "allowances": {"bonus": 5000.0},
            "deductions": {"tax": 1000.0},
            "effective_from": str(date.today())
        }
        resp = await client.post(f"staff/{staff_id}/salary-structures", json=salary_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Add salary structure failed: {resp.status_code} - {resp.text}")
        else:
            print(f"Salary structure added successfully.")

        print("\n=== 3. Record Attendance ===")
        attendance_payload = {
            "staff_id": staff_id,
            "date": str(date.today()),
            "status": "present",
            "notes": "On time"
        }
        resp = await client.post("staff/attendance", json=attendance_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Record attendance failed: {resp.status_code} - {resp.text}")
        else:
            print("Attendance recorded successfully.")

        print("\n=== 4. Give Advance ===")
        current_month = date.today().month
        current_year = date.today().year
        advance_payload = {
            "staff_id": staff_id,
            "amount": 2000.0,
            "deduct_from_month": current_month,
            "deduct_from_year": current_year,
            "reason": "Emergency"
        }
        resp = await client.post("staff/advances", json=advance_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Give advance failed: {resp.status_code} - {resp.text}")
        else:
            print("Advance recorded successfully.")

        print("\n=== 5. Disburse Salary ===")
        # We need an account_id. Let's create one first.
        acc_payload = {"name": f"Bank {timestamp}", "account_type": "bank", "bank_name": "Test Bank"}
        acc_resp = await client.post("transactions/accounts", json=acc_payload, headers=headers)
        account_id = acc_resp.json()["data"]["id"] if acc_resp.status_code == 201 else None

        if not account_id:
            print("Failed to create account for salary payment")
            return

        payment_payload = {
            "staff_id": staff_id,
            "payment_month": current_month,
            "payment_year": current_year,
            "gross_salary": 50000.0,
            "total_allowances": 5000.0,
            "total_deductions": 1000.0,
            "advance_deduction": 2000.0, # advance taken this month
            "payment_mode": "bank",
            "account_id": account_id,
            "notes": "Monthly Salary"
        }
        resp = await client.post("staff/payments", json=payment_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Disburse salary failed: {resp.status_code} - {resp.text}")
        else:
            data = resp.json()["data"]
            print(f"Salary disbursed successfully. Net Salary: {data['net_salary']}")

        print("\n=== Validation Complete! ===")

if __name__ == "__main__":
    asyncio.run(validate_staff_module())
