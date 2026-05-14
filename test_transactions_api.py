import asyncio
import httpx
from datetime import datetime, date

BASE_URL = "http://127.0.0.1:8000/api/v1/"

async def validate_transactions():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("=== 0. Login ===")
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} - {resp.text}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print("\n=== 1. Create Accounts ===")
        timestamp = int(datetime.now().timestamp())
        
        async def create_account(name, type, bank=None):
            payload = {"name": f"{name} {timestamp}", "account_type": type}
            if bank: payload["bank_name"] = bank
            resp = await client.post("transactions/accounts", json=payload, headers=headers)
            if resp.status_code == 201:
                return resp.json()["data"]
            print(f"Failed to create account {name}: {resp.status_code} - {resp.text}")
            return None

        cash_acc = await create_account("Main Cash", "cash")
        bank_acc = await create_account("HBL Savings", "bank", "HBL")

        if not cash_acc or not bank_acc:
            print("Account setup failed.")
            return
        
        print(f"Accounts created: {cash_acc['name']} (ID:{cash_acc['id']}), {bank_acc['name']} (ID:{bank_acc['id']})")

        # 2. Record Initial Transaction (Opening Balance adjustment)
        print("\n=== 2. Record Manual Transaction (Credit) ===")
        # Note: Usually opening balance is part of account creation, but let's test manual record if exists
        # According to the user, there is no direct POST /transactions, but record_account_transaction service exists.
        # Let's see if there is an endpoint for manual transaction record.
        # User mentioned: "5 for accounts (create, list, detail, update, deactivate + transaction history)"
        # This implies no direct manual transaction POST. Transactions usually come from Purchases/Sales or Transfers.
        
        # 3. Test Transfer
        print("\n=== 3. Create Transfer (Cash -> Bank) ===")
        # We need some balance in cash first. Since we can't record manually, let's see if we can create a transfer with 0 balance (it might fail if checked).
        # Actually, let's try to create a transfer of 1000.
        transfer_payload = {
            "from_account_id": cash_acc["id"],
            "to_account_id": bank_acc["id"],
            "amount": 1000,
            "reference_no": f"TX-{timestamp}",
            "notes": "Initial transfer for validation"
        }
        tr_resp = await client.post("transactions/transfers", json=transfer_payload, headers=headers)
        if tr_resp.status_code != 201:
            print(f"Transfer failed (Expected if no balance): {tr_resp.status_code} - {tr_resp.text}")
            # If it failed due to balance, that's actually a good sign of validation.
        else:
            print(f"Transfer successful! ID: {tr_resp.json()['data']['id']}")

        # 4. Verify Account Balances & History
        print("\n=== 4. Verify Balances & History ===")
        for acc_id in [cash_acc["id"], bank_acc["id"]]:
            acc_resp = await client.get(f"transactions/accounts/{acc_id}", headers=headers)
            acc_data = acc_resp.json()["data"]
            print(f"Account: {acc_data['name']}, Balance: {acc_data['balance']}")
            
            hist_resp = await client.get(f"transactions/accounts/{acc_id}/transactions", headers=headers)
            print(f"  Transaction count: {len(hist_resp.json()['data'])}")

        print("\n=== Validation Complete! ===")

if __name__ == "__main__":
    asyncio.run(validate_transactions())
