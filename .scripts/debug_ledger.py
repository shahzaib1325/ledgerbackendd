import httpx
from decimal import Decimal

BASE_URL = "http://localhost:8000/api/v1"

def debug_customer_ledger():
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)
    
    # 1. Login (assuming the tester user from previous run exists)
    # We can fetch the username from the list or just use the last one if we remember it.
    # To be safe, I'll just skip auth if I can or use a known one.
    # Since I don't have the exact username handy (it was uuid based), 
    # I'll just register a new one and create a new customer to be sure.
    
    username = "debug_user"
    password = "P@ssword123!"
    
    client.post("/auth/register", json={
        "username": username,
        "email": "debug@example.com",
        "password": password,
        "full_name": "Debugger"
    })
    
    # Promote
    import subprocess, sys
    subprocess.run([sys.executable, "promote_user.py", username])
    
    login = client.post("/auth/login", json={"username": username, "password": password})
    client.headers["Authorization"] = f"Bearer {login.json()['data']['tokens']['access_token']}"
    
    # 2. Create customer
    payload = {
        "name": "Debug Customer",
        "opening_balance": 1000,
        "balance_type": "receivable"
    }
    resp = client.post("/customers", json=payload)
    cid = resp.json()["data"]["id"]
    
    # 3. Payments
    client.post(f"/customers/{cid}/payments", json={"amount": 300, "payment_mode": "cash"})
    client.post(f"/customers/{cid}/payments", json={"amount": 800, "payment_mode": "cash"})
    
    # 4. Get Ledger and PRINT
    ledger = client.get(f"/customers/{cid}/ledger")
    print("\n--- DEBUG LEDGER ---")
    for i, item in enumerate(ledger.json()["data"]):
        print(f"Row {i}: Type={item['reference_type']}, Debit={item['debit']}, Credit={item['credit']}, Balance={item['balance']} {item['balance_type']}")

if __name__ == "__main__":
    debug_customer_ledger()
