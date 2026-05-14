import httpx
from decimal import Decimal
import uuid
import subprocess
import sys

BASE_URL = "http://localhost:8000/api/v1"

def test_receivable_ledger():
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    username = f"rec_test_{uuid.uuid4().hex[:8]}"
    
    # 1. Register
    client.post("/auth/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "P@ssword123!",
        "full_name": "Rec Test"
    })
    
    # 2. Promote
    subprocess.run([sys.executable, "promote_user.py", username], check=True)
    
    # 3. Login
    resp = client.post("/auth/login", json={"username": username, "password": "P@ssword123!"})
    token = resp.json()["data"]["tokens"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    
    # 4. Create Receivable Supplier
    # 1000 receivable means the supplier owes US. Signed balance = -1000.
    resp = client.post("/suppliers", json={
        "name": "Receivable Supplier",
        "opening_balance": 1000,
        "balance_type": "receivable"
    })
    sid = resp.json()["data"]["id"]
    print(f"Created Supplier {sid}: balance {resp.json()['data']['balance']} {resp.json()['data']['balance_type']}")
    
    # 5. Record 300 payment (We pay them more)
    # New balance should be 1300 receivable (signed -1300).
    client.post(f"/suppliers/{sid}/payments", json={"amount": 300, "payment_mode": "cash"})
    
    # 6. Check Balance
    resp = client.get(f"/suppliers/{sid}/balance")
    data = resp.json()["data"]
    print(f"Current Balance: {data['balance']} {data['balance_type']}")
    
    # 7. Check Ledger
    resp = client.get(f"/suppliers/{sid}/ledger")
    items = resp.json()["data"]
    print("Ledger:")
    for i in items:
        print(f" - {i['description']}: Debit {i['debit']}, Credit {i['credit']}, Balance {i['balance']}")

if __name__ == "__main__":
    test_receivable_ledger()
