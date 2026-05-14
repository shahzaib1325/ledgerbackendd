import httpx
import asyncio
import json

BASE_URL = "http://localhost:8000"

async def test_all():
    async with httpx.AsyncClient() as client:
        # 1. Health
        print("Testing Health...")
        try:
            resp = await client.get(f"{BASE_URL}/health")
            print(f"Health status: {resp.status_code}, body: {resp.text}")
        except Exception as e:
            print(f"Health failed: {e}")

        # 2. Register
        print("\nTesting Registration...")
        reg_payload = {
            "username": "testadmin_final",
            "email": "testadmin_final@example.com",
            "password": "Password123!",
            "full_name": "Test Admin"
        }
        resp = await client.post(f"{BASE_URL}/api/v1/auth/register", json=reg_payload)
        print(f"Register status: {resp.status_code}, body: {resp.text}")
        
        # If user exists, we might get 409, that's fine.
        
        # 3. Login
        print("\nTesting Login...")
        login_payload = {
            "username": "testadmin_final",
            "password": "Password123!"
        }
        resp = await client.post(f"{BASE_URL}/api/v1/auth/login", json=login_payload)
        print(f"Login status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()["data"]
            token = data["tokens"]["access_token"]
            print("Login successful, token obtained.")
            headers = {"Authorization": f"Bearer {token}"}
            
            # 4. List Suppliers
            print("\nTesting List Suppliers...")
            resp = await client.get(f"{BASE_URL}/api/v1/suppliers", headers=headers)
            print(f"List Suppliers status: {resp.status_code}, body: {resp.text}")

            # 5. Create Supplier
            print("\nTesting Create Supplier...")
            supplier_payload = {
                "name": "Global Tech",
                "email": "contact@globaltech.com",
                "phone": "1234567890",
                "address": "123 Tech Lane",
                "balance_type": "payable",
                "opening_balance": 1000.0,
                "cr_limit": 5000.0
            }
            resp = await client.post(f"{BASE_URL}/api/v1/suppliers", json=supplier_payload, headers=headers)
            print(f"Create Supplier status: {resp.status_code}, body: {resp.text}")
            
            if resp.status_code == 201:
                supplier_id = resp.json()["data"]["id"]
                
                # 6. Get Supplier
                print(f"\nTesting Get Supplier {supplier_id}...")
                resp = await client.get(f"{BASE_URL}/api/v1/suppliers/{supplier_id}", headers=headers)
                print(f"Get Supplier status: {resp.status_code}, body: {resp.text}")
        else:
            print("Login failed, skipping protected endpoints.")

if __name__ == "__main__":
    asyncio.run(test_all())
