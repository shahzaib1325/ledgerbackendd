import httpx
import asyncio
import time
from decimal import Decimal
import sys
import uuid
import subprocess

BASE_URL = "http://localhost:8000/api/v1"

class CustomerValidator:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=30.0)
        self.token = None
        self.customer_id = None
        self.username = f"tester_{uuid.uuid4().hex[:8]}"
        self.password = "P@ssword123!"
        self.results = []

    def log(self, phase, step, result, message=""):
        res = {"phase": phase, "step": step, "result": result, "message": message}
        self.results.append(res)
        color = "\033[92m" if result == "PASS" else "\033[91m"
        reset = "\033[0m"
        print(f"[{phase}] {step}: {color}{result}{reset} {message}")

    def run_phase_1_auth(self):
        print("\n--- PHASE 1: AUTH ---")
        resp = self.client.post("/auth/register", json={
            "username": self.username,
            "email": f"{self.username}@example.com",
            "password": self.password,
            "full_name": "Customer Validator"
        })
        if resp.status_code == 201:
            self.log("PHASE 1", "Register", "PASS")
            print(f"Promoting {self.username} to admin...")
            try:
                subprocess.run([sys.executable, "promote_user.py", self.username], check=True)
                self.log("PHASE 1", "Promote User", "PASS")
            except subprocess.CalledProcessError as e:
                self.log("PHASE 1", "Promote User", "FAIL", f"Error: {e}")
                return False
        else:
            self.log("PHASE 1", "Register", "FAIL", f"Status: {resp.status_code}, Body: {resp.text}")
            return False

        resp = self.client.post("/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        if resp.status_code == 200:
            self.token = resp.json()["data"]["tokens"]["access_token"]
            self.client.headers["Authorization"] = f"Bearer {self.token}"
            self.log("PHASE 1", "Login", "PASS")
            return True
        else:
            self.log("PHASE 1", "Login", "FAIL", f"Status: {resp.status_code}")
            return False

    def run_phase_2_baseline(self):
        print("\n--- PHASE 2: CUSTOMER BASELINE ---")
        payload = {
            "name": "Test Customer",
            "opening_balance": 1000,
            "balance_type": "receivable",
            "credit_limit": 5000
        }
        resp = self.client.post("/customers", json=payload)
        if resp.status_code == 201:
            data = resp.json()["data"]
            self.customer_id = data["id"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("1000") and data["balance_type"] == "receivable":
                self.log("PHASE 2", "Create Customer", "PASS")
            else:
                self.log("PHASE 2", "Create Customer", "FAIL", f"Balance: {data['balance']} {data['balance_type']}")
        else:
            self.log("PHASE 2", "Create Customer", "FAIL", f"Status: {resp.status_code}")
            return False

        resp = self.client.get(f"/customers/{self.customer_id}")
        if resp.status_code == 200:
            self.log("PHASE 2", "Get Customer", "PASS")
        else:
            self.log("PHASE 2", "Get Customer", "FAIL")

        resp = self.client.get(f"/customers/{self.customer_id}/balance")
        if resp.status_code == 200:
            data = resp.json()["data"]
            if Decimal(str(data["balance"])) == Decimal("1000") and data["balance_type"] == "receivable":
                self.log("PHASE 2", "Balance Summary", "PASS")
            else:
                self.log("PHASE 2", "Balance Summary", "FAIL")
        return True

    def run_phase_3_payment_flow(self):
        print("\n--- PHASE 3: PAYMENT FLOW ---")
        # Payment 300 reduces receivable (1000 -> 700)
        resp = self.client.post(f"/customers/{self.customer_id}/payments", json={
            "amount": 300,
            "payment_mode": "cash"
        })
        if resp.status_code == 201:
            b_resp = self.client.get(f"/customers/{self.customer_id}/balance")
            balance = Decimal(str(b_resp.json()["data"]["balance"]))
            if balance == Decimal("700") and b_resp.json()["data"]["balance_type"] == "receivable":
                self.log("PHASE 3", "Payment #1 (300)", "PASS", "Balance = 700 receivable")
            else:
                self.log("PHASE 3", "Payment #1 (300)", "FAIL", f"Balance: {balance}")
        
        # Payment 800 flips to payable (700 -> -100 -> 100 payable)
        resp = self.client.post(f"/customers/{self.customer_id}/payments", json={
            "amount": 800,
            "payment_mode": "cash"
        })
        if resp.status_code == 201:
            b_resp = self.client.get(f"/customers/{self.customer_id}/balance")
            data = b_resp.json()["data"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("100") and data["balance_type"] == "payable":
                self.log("PHASE 3", "Payment #2 (800) - Overpayment", "PASS", "Balance = 100 payable (FLIPPED)")
            else:
                self.log("PHASE 3", "Payment #2 (800) - Overpayment", "FAIL", f"Balance: {balance} {data['balance_type']}")
        return True

    def run_phase_5_ledger_validation(self):
        print("\n--- PHASE 5: LEDGER VALIDATION ---")
        resp = self.client.get(f"/customers/{self.customer_id}/ledger")
        if resp.status_code == 200:
            items = resp.json()["data"]
            if len(items) != 3:
                self.log("PHASE 5", "Ledger Row Count", "FAIL", f"Expected 3 rows (Opening + 2 payments), found {len(items)}")
                return False

            # Check Opening
            it0 = items[0]
            if it0["reference_type"] == "opening" and Decimal(str(it0["balance"])) == Decimal("1000"):
                self.log("PHASE 5", "Opening Row", "PASS")
            else:
                self.log("PHASE 5", "Opening Row", "FAIL")

            # Check Overpayment Flip
            it2 = items[2]
            if it2["balance_type"] == "payable" and Decimal(str(it2["balance"])) == Decimal("100"):
                self.log("PHASE 5", "Ledger Flip Check", "PASS")
            else:
                self.log("PHASE 5", "Ledger Flip Check", "FAIL")
            return True
        return False

    def run_phase_7_soft_delete(self):
        print("\n--- PHASE 7: SOFT DELETE ---")
        resp = self.client.delete(f"/customers/{self.customer_id}")
        if resp.status_code == 200:
            self.log("PHASE 7", "Delete Customer", "PASS")
            r_get = self.client.get(f"/customers/{self.customer_id}")
            if r_get.status_code == 404:
                self.log("PHASE 7", "Verify 404", "PASS")
            else:
                self.log("PHASE 7", "Verify 404", "FAIL")
        return True

    def run_all(self):
        if not self.run_phase_1_auth(): return
        self.run_phase_2_baseline()
        self.run_phase_3_payment_flow()
        self.run_phase_5_ledger_validation()
        self.run_phase_7_soft_delete()
        
        print("\n" + "="*50)
        print("CUSTOMER VALIDATION SUMMARY")
        print("="*50)
        total = len(self.results)
        passed = sum(1 for r in self.results if r["result"] == "PASS")
        print(f"TOTAL TESTS: {total}")
        print(f"PASSED:      {passed}")
        print(f"FAILED:      {total - passed}")

if __name__ == "__main__":
    validator = CustomerValidator()
    validator.run_all()
