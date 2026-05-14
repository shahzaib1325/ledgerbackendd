import asyncio
import httpx
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000/api/v1/"

async def validate_purchases():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        print("=== 0. Login ===")
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Setup prerequisite data
        print("\n=== 1. Setup Unit, Category, Item, Supplier ===")
        
        async def get_or_create(path, payload):
            resp = await client.post(path, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                return resp.json()["data"]["id"]
            if resp.status_code == 409:
                # If conflict, try to list and find it (simple hack for validation)
                list_resp = await client.get(path, headers=headers)
                for item in list_resp.json()["data"]:
                    if item.get("name") == payload["name"] or item.get("abbreviation") == payload.get("abbreviation"):
                        return item["id"]
            print(f"Failed to setup {path}: {resp.status_code} - {resp.text}")
            return None

        unit_id = await get_or_create("inventory/units", {"name": "Test Pack", "abbreviation": "tpk"})
        cat_id = await get_or_create("inventory/categories", {"name": "Test Raw Materials"})
        
        timestamp = int(datetime.now().timestamp())
        item_id = await get_or_create("inventory/items", {
            "name": f"Validation Item {timestamp}",
            "sku": f"VAL-{timestamp}",
            "unit_id": unit_id,
            "category_id": cat_id,
            "item_type": "purchased"
        })
        
        supplier_id = await get_or_create("suppliers", {
            "name": f"Validation Supplier {timestamp}",
            "phone": f"98765{str(timestamp)[-5:]}",
            "balance_type": "payable",
            "opening_balance": 0
        })

        if not all([unit_id, cat_id, item_id, supplier_id]):
            print("Setup failed. Cannot continue.")
            return

        print(f"Setup complete: Unit:{unit_id}, Cat:{cat_id}, Item:{item_id}, Supplier:{supplier_id}")

        # 2. Create Purchase
        print("\n=== 2. Create Draft Purchase ===")
        purchase_payload = {
            "supplier_id": supplier_id,
            "invoice_no": "INV-TEST-001",
            "payment_type": "credit",
            "items": [
                {
                    "item_id": item_id,
                    "unit_id": unit_id,
                    "quantity": 10,
                    "unit_price": 50
                }
            ]
        }
        p_resp = await client.post("purchases", json=purchase_payload, headers=headers)
        if p_resp.status_code != 201:
            print(f"Failed to create purchase: {p_resp.status_code} - {p_resp.text}")
            return
        purchase = p_resp.json()["data"]
        purchase_id = purchase["id"]
        print(f"Draft Purchase created ID: {purchase_id}, Status: {purchase['status']}")

        # 3. Confirm Purchase
        print("\n=== 3. Confirm Purchase ===")
        confirm_resp = await client.post(f"purchases/{purchase_id}/confirm", headers=headers)
        if confirm_resp.status_code != 200:
            print(f"Failed to confirm purchase: {confirm_resp.status_code} - {confirm_resp.text}")
            return
        print(f"Purchase confirmed! New Status: {confirm_resp.json()['data']['status']}")

        # 4. Verify Stock Movement
        print("\n=== 4. Verify Stock ===")
        stock_resp = await client.get(f"inventory/items/{item_id}", headers=headers)
        current_stock = stock_resp.json()["data"]["current_stock"]
        print(f"Item Stock after confirmation: {current_stock} (Expected: 10.000)")

        print("\n=== Validation Complete! ===")

if __name__ == "__main__":
    asyncio.run(validate_purchases())
