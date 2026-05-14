import httpx
import asyncio
import time
from decimal import Decimal
import sys
import uuid
import subprocess

BASE_URL = "http://localhost:8000/api/v1"

class SupplierValidator:
    def __init__(self):
        self.client = httpx.Client(base_url=BASE_URL, timeout=30.0)
        self.token = None
        self.supplier_id = None
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
        # 1. Register
        resp = self.client.post("/auth/register", json={
            "username": self.username,
            "email": f"{self.username}@example.com",
            "password": self.password,
            "full_name": "Test Validator"
        })
        if resp.status_code == 201:
            self.log("PHASE 1", "Register", "PASS")
            
            # PROMOTION STEP
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

        # 2. Login
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
            self.log("PHASE 1", "Login", "FAIL", f"Status: {resp.status_code}, Body: {resp.text}")
            return False

    def run_phase_2_baseline(self):
        print("\n--- PHASE 2: SUPPLIER BASELINE ---")
        # 1. Create Supplier
        payload = {
            "name": "Test Supplier",
            "opening_balance": 1000,
            "balance_type": "payable"
        }
        resp = self.client.post("/suppliers", json=payload)
        if resp.status_code == 201:
            data = resp.json()["data"]
            self.supplier_id = data["id"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("1000") and data["balance_type"] == "payable":
                self.log("PHASE 2", "Create Supplier", "PASS")
            else:
                self.log("PHASE 2", "Create Supplier", "FAIL", f"Unexpected balance: {data['balance']} {data['balance_type']}")
        else:
            self.log("PHASE 2", "Create Supplier", "FAIL", f"Status: {resp.status_code}")
            return False

        # 2. Get Supplier
        resp = self.client.get(f"/suppliers/{self.supplier_id}")
        if resp.status_code == 200:
            self.log("PHASE 2", "Get Supplier", "PASS")
        else:
            self.log("PHASE 2", "Get Supplier", "FAIL")

        # 3. Get Balance Summary
        resp = self.client.get(f"/suppliers/{self.supplier_id}/balance")
        if resp.status_code == 200:
            data = resp.json()["data"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("1000") and data["balance_type"] == "payable":
                self.log("PHASE 2", "Balance Summary", "PASS")
            else:
                self.log("PHASE 2", "Balance Summary", "FAIL", f"Balance: {data['balance']}")
        else:
            self.log("PHASE 2", "Balance Summary", "FAIL")
        return True

    def run_phase_3_payment_flow(self):
        print("\n--- PHASE 3: PAYMENT FLOW ---")
        # 1. Record Payment #1 (300)
        resp = self.client.post(f"/suppliers/{self.supplier_id}/payments", json={
            "amount": 300,
            "payment_mode": "cash"
        })
        if resp.status_code == 201:
            # Verify balance via summary
            b_resp = self.client.get(f"/suppliers/{self.supplier_id}/balance")
            data = b_resp.json()["data"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("700") and data["balance_type"] == "payable":
                self.log("PHASE 3", "Payment #1 (300)", "PASS", "Balance = 700 payable")
            else:
                self.log("PHASE 3", "Payment #1 (300)", "FAIL", f"Balance: {data['balance']} {data['balance_type']}")
        else:
            self.log("PHASE 3", "Payment #1 (300)", "FAIL", f"Status Code: {resp.status_code}")

        # 2. Record Payment #2 (800 - OVERPAYMENT)
        resp = self.client.post(f"/suppliers/{self.supplier_id}/payments", json={
            "amount": 800,
            "payment_mode": "cash"
        })
        if resp.status_code == 201:
            # Verify balance flip
            b_resp = self.client.get(f"/suppliers/{self.supplier_id}/balance")
            data = b_resp.json()["data"]
            balance = Decimal(str(data["balance"]))
            if balance == Decimal("100") and data["balance_type"] == "receivable":
                self.log("PHASE 3", "Payment #2 (800) - Overpayment", "PASS", "Balance = 100 receivable (FLIPPED)")
            else:
                self.log("PHASE 3", "Payment #2 (800) - Overpayment", "FAIL", f"Balance: {data['balance']} {data['balance_type']}")
        else:
            self.log("PHASE 3", "Payment #2 (800)", "FAIL", f"Status Code: {resp.status_code}")
        return True

    def run_phase_4_payment_history(self):
        print("\n--- PHASE 4: PAYMENT HISTORY ---")
        resp = self.client.get(f"/suppliers/{self.supplier_id}/payments")
        if resp.status_code == 200:
            items = resp.json()["data"] # FIXED: PaginatedResponse has 'data'
            amounts = [Decimal(str(i["amount"])) for i in items]
            if len(items) == 2 and Decimal("300") in amounts and Decimal("800") in amounts:
                self.log("PHASE 4", "List Payments", "PASS", f"Found 2 payments: {amounts}")
            else:
                self.log("PHASE 4", "List Payments", "FAIL", f"Found {len(items)} payments: {amounts}")
        else:
            self.log("PHASE 4", "List Payments", "FAIL", f"Status: {resp.status_code}")
        return True

    def run_phase_5_ledger_validation(self):
        print("\n--- PHASE 5: LEDGER VALIDATION ---")
        resp = self.client.get(f"/suppliers/{self.supplier_id}/ledger")
        if resp.status_code == 200:
            items = resp.json()["data"]
            
            # Expected sequence: 
            # 0: Opening (1000 payable)
            # 1: Payment (700 payable)
            # 2: Payment (100 receivable)
            
            if len(items) != 3:
                self.log("PHASE 5", "Ledger Row Count", "FAIL", f"Expected 3 rows, found {len(items)}")
                return False

            pass_count = 0
            
            # 1. Opening Row
            it0 = items[0]
            it0_bal = Decimal(str(it0["balance"]))
            if it0["reference_type"] == "opening" and it0_bal == Decimal("1000") and it0["balance_type"] == "payable":
                self.log("PHASE 5", "Step 1 (Opening)", "PASS")
                pass_count += 1
            else:
                self.log("PHASE 5", "Step 1 (Opening)", "FAIL", f"Type: {it0['reference_type']}, Bal: {it0_bal} {it0['balance_type']}")

            # 2. Payment 300
            it1 = items[1]
            it1_bal = Decimal(str(it1["balance"]))
            if it1["debit"] == 300 and it1_bal == Decimal("700") and it1["balance_type"] == "payable":
                self.log("PHASE 5", "Step 2 (Payment 300)", "PASS")
                pass_count += 1
            else:
                self.log("PHASE 5", "Step 2 (Payment 300)", "FAIL", f"Bal: {it1_bal} {it1['balance_type']}")

            # 3. Payment 800
            it2 = items[2]
            it2_bal = Decimal(str(it2["balance"]))
            if it2["debit"] == 800 and it2_bal == Decimal("100") and it2["balance_type"] == "receivable":
                self.log("PHASE 5", "Step 3 (Payment 800)", "PASS")
                pass_count += 1
            else:
                self.log("PHASE 5", "Step 3 (Payment 800)", "FAIL", f"Bal: {it2_bal} {it2['balance_type']}")

            # 4. Consistency Check
            b_resp = self.client.get(f"/suppliers/{self.supplier_id}/balance")
            cached = b_resp.json()["data"]
            cached_balance = Decimal(str(cached["balance"]))
            
            if cached_balance == it2_bal and cached["balance_type"] == it2["balance_type"]:
                self.log("PHASE 5", "Consistency Check", "PASS", f"Cached balance matches ledger final row: {cached_balance} {cached['balance_type']}")
                pass_count += 1
            else:
                self.log("PHASE 5", "Consistency Check", "FAIL", f"Cached: {cached_balance} {cached['balance_type']}, Ledger: {it2_bal} {it2['balance_type']}")

            return pass_count == 4
        else:
            self.log("PHASE 5", "Ledger Validation", "FAIL", f"Status: {resp.status_code}")
            return False

    def run_phase_6_update(self):
        print("\n--- PHASE 6: UPDATE ---")
        resp = self.client.patch(f"/suppliers/{self.supplier_id}", json={"name": "Updated Supplier"})
        if resp.status_code == 200:
            data = resp.json()["data"]
            balance = Decimal(str(data["balance"]))
            if data["name"] == "Updated Supplier" and balance == Decimal("100"):
                self.log("PHASE 6", "Update Supplier", "PASS")
            else:
                self.log("PHASE 6", "Update Supplier", "FAIL", f"Name: {data['name']}, Balance: {data['balance']}")
        else:
            self.log("PHASE 6", "Update Supplier", "FAIL")
        return True

    def run_phase_7_soft_delete(self):
        print("\n--- PHASE 7: SOFT DELETE ---")
        resp = self.client.delete(f"/suppliers/{self.supplier_id}")
        if resp.status_code == 403:
            self.log("PHASE 7", "Delete Supplier", "SKIP", "Permission Denied (Require Admin)")
            return True
        
        if resp.status_code == 200:
            self.log("PHASE 7", "Delete Supplier", "PASS")
            
            # 1. Fetch should 404
            r_get = self.client.get(f"/suppliers/{self.supplier_id}")
            if r_get.status_code == 404:
                self.log("PHASE 7", "Verify GET 404", "PASS")
            else:
                self.log("PHASE 7", "Verify GET 404", "FAIL", f"Got status {r_get.status_code}")

            # 2. List should not find it
            r_list = self.client.get("/suppliers?is_active=true")
            ids = [s["id"] for s in r_list.json()["data"]] # FIXED
            if self.supplier_id not in ids:
                self.log("PHASE 7", "Verify Exclusion from List", "PASS")
            else:
                self.log("PHASE 7", "Verify Exclusion from List", "FAIL")
        else:
            self.log("PHASE 7", "Delete Supplier", "FAIL", f"Status: {resp.status_code}")
        return True

    def run_phase_8_edge_cases(self):
        print("\n--- PHASE 8: EDGE CASES ---")
        # Create a fresh supplier for edge cases
        payload = {"name": "Edge Case Supplier", "opening_balance": 0}
        resp = self.client.post("/suppliers", json=payload)
        sid = resp.json()["data"]["id"]

        # 1. Zero Payment
        r0 = self.client.post(f"/suppliers/{sid}/payments", json={"amount": 0, "payment_mode": "cash"})
        if r0.status_code in (400, 422):
            self.log("PHASE 8", "Zero Payment", "PASS", "Rejected as expected")
        else:
            self.log("PHASE 8", "Zero Payment", "FAIL", f"Status: {r0.status_code}")

        # 2. Negative Payment
        rn = self.client.post(f"/suppliers/{sid}/payments", json={"amount": -100, "payment_mode": "cash"})
        if rn.status_code in (400, 422):
            self.log("PHASE 8", "Negative Payment", "PASS", "Rejected as expected")
        else:
            self.log("PHASE 8", "Negative Payment", "FAIL", f"Status: {rn.status_code}")

        # 3. Large Payment
        rl = self.client.post(f"/suppliers/{sid}/payments", json={"amount": 99999999, "payment_mode": "cash"})
        if rl.status_code == 201:
            self.log("PHASE 8", "Large Payment", "PASS", "Accepted")
        else:
            self.log("PHASE 8", "Large Payment", "FAIL", f"Status: {rl.status_code}")
        return True

    async def run_bonus_concurrency(self):
        print("\n--- BONUS: CONCURRENCY ---")
        # Create a fresh supplier
        payload = {"name": "Concurrency Test", "opening_balance": 2000}
        resp = self.client.post("/suppliers", json=payload)
        sid = resp.json()["data"]["id"]
        
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self.client.headers) as aclient:
            tasks = [
                aclient.post(f"/suppliers/{sid}/payments", json={"amount": 500, "payment_mode": "cash"}),
                aclient.post(f"/suppliers/{sid}/payments", json={"amount": 700, "payment_mode": "cash"})
            ]
            responses = await asyncio.gather(*tasks)
            
        success_count = sum(1 for r in responses if r.status_code == 201)
        self.log("BONUS", "Parallel Requests", "PASS" if success_count == 2 else "FAIL", f"Success: {success_count}/2")
        
        # Verify final balance
        resp = self.client.get(f"/suppliers/{sid}/balance")
        data = resp.json()["data"]
        balance = Decimal(str(data["balance"]))
        if balance == Decimal("800"):
            self.log("BONUS", "Final Balance", "PASS", "Balance = 800")
        else:
            self.log("BONUS", "Final Balance", "FAIL", f"Got {data['balance']}")

    def run_all(self):
        if not self.run_phase_1_auth(): return
        self.run_phase_2_baseline()
        self.run_phase_3_payment_flow()
        self.run_phase_4_payment_history()
        self.run_phase_5_ledger_validation()
        self.run_phase_6_update()
        self.run_phase_7_soft_delete()
        self.run_phase_8_edge_cases()
        asyncio.run(self.run_bonus_concurrency())
        
        print("\n" + "="*50)
        print("VALIDATION SUMMARY")
        print("="*50)
        total = len(self.results)
        passed = sum(1 for r in self.results if r["result"] == "PASS")
        skipped = sum(1 for r in self.results if r["result"] == "SKIP")
        failed = total - passed - skipped
        print(f"TOTAL TESTS: {total}")
        print(f"PASSED:      {passed}")
        print(f"FAILED:      {failed}")
        print(f"SKIPPED:     {skipped}")
        
        if failed > 0:
            print("\nFAILURES:")
            for r in self.results:
                if r["result"] == "FAIL":
                    print(f"- {r['phase']} {r['step']}: {r['message']}")

if __name__ == "__main__":
    validator = SupplierValidator()
    validator.run_all()
