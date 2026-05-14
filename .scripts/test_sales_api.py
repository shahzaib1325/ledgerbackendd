import asyncio
import httpx
from datetime import datetime, date

BASE_URL = "http://127.0.0.1:8000/api/v1/"

async def validate_sales():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("=== 0. Login ===")
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} - {resp.text}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Setup prerequisite data
        print("\n=== 1. Setup Unit, Category, Item, Customer ===")
        
        async def get_or_create(path, payload):
            resp = await client.post(path, json=payload, headers=headers)
            if resp.status_code in (200, 201):
                return resp.json()["data"]["id"]
            if resp.status_code == 409:
                list_resp = await client.get(path, headers=headers)
                data = list_resp.json().get("data", [])
                if isinstance(data, dict) and "items" in data:
                    data = data["items"]
                for item in data:
                    if item.get("name") == payload["name"] or item.get("abbreviation") == payload.get("abbreviation") or item.get("sku") == payload.get("sku"):
                        return item["id"]
            print(f"Failed to setup {path}: {resp.status_code} - {resp.text}")
            return None

        unit_id = await get_or_create("inventory/units", {"name": "Test Sale Box", "abbreviation": "sbx"})
        cat_id = await get_or_create("inventory/categories", {"name": "Finished Goods"})
        
        timestamp = int(datetime.now().timestamp())
        item_id = await get_or_create("inventory/items", {
            "name": f"Sale Item {timestamp}",
            "sku": f"SALE-{timestamp}",
            "unit_id": unit_id,
            "category_id": cat_id,
            "item_type": "produced"
        })
        
        customer_id = await get_or_create("customers", {
            "name": f"Validation Customer {timestamp}",
            "phone": f"12345{str(timestamp)[-5:]}",
            "balance_type": "receivable",
            "opening_balance": 0
        })

        if not all([unit_id, cat_id, item_id, customer_id]):
            print("Setup failed. Cannot continue.")
            return

        # Prerequisite: Adjust stock so we have something to sell
        print("\n=== 1.1 Adjust Stock (Add 100) ===")
        adj_resp = await client.post(f"inventory/items/{item_id}/adjust", json={
            "item_id": item_id,
            "quantity": 100,
            "note": "Initial stock for sale validation"
        }, headers=headers)
        if adj_resp.status_code != 201:
            print(f"Stock adjustment failed: {adj_resp.status_code} - {adj_resp.text}")
            return

        print(f"Setup complete: Unit:{unit_id}, Cat:{cat_id}, Item:{item_id}, Customer:{customer_id}")

        # 2. Create Sale
        print("\n=== 2. Create Draft Sale ===")
        sale_payload = {
            "customer_id": customer_id,
            "invoice_no": f"INV-SALE-{timestamp}",
            "payment_type": "credit",
            "items": [
                {
                    "item_id": item_id,
                    "unit_id": unit_id,
                    "quantity": 5,
                    "unit_price": 100
                }
            ]
        }
        s_resp = await client.post("sales", json=sale_payload, headers=headers)
        if s_resp.status_code != 201:
            print(f"Failed to create sale: {s_resp.status_code} - {s_resp.text}")
            return
        sale = s_resp.json()["data"]
        sale_id = sale["id"]
        print(f"Draft Sale created ID: {sale_id}, Status: {sale['status']}")

        # 3. Confirm Sale
        print("\n=== 3. Confirm Sale ===")
        confirm_resp = await client.post(f"sales/{sale_id}/confirm", headers=headers)
        if confirm_resp.status_code != 200:
            print(f"Failed to confirm sale: {confirm_resp.status_code} - {confirm_resp.text}")
            return
        print(f"Sale confirmed! New Status: {confirm_resp.json()['data']['status']}")

        # 4. Verify Stock & Customer Balance
        print("\n=== 4. Verify Stock & Balance ===")
        stock_resp = await client.get(f"inventory/items/{item_id}", headers=headers)
        current_stock = stock_resp.json()["data"]["current_stock"]
        print(f"Item Stock after sale: {current_stock} (Expected: 95.000)")

        cust_resp = await client.get(f"customers/{customer_id}", headers=headers)
        balance = cust_resp.json()["data"]["balance"]
        print(f"Customer Balance after sale: {balance} (Expected: 500.00)")

        # 5. Record Payment
        print("\n=== 5. Record Payment (Partial) ===")
        pay_resp = await client.post(f"sales/{sale_id}/payments", json={
            "amount": 200,
            "payment_mode": "cash"
        }, headers=headers)
        if pay_resp.status_code != 201:
            print(f"Failed to record payment: {pay_resp.status_code} - {pay_resp.text}")
        else:
            print(f"Payment recorded! New Invoice Status: {pay_resp.json()['data'].get('status', 'check detail')} (check detail for updated status)")
            # Re-fetch sale to see status change
            detail_resp = await client.get(f"sales/{sale_id}", headers=headers)
            print(f"Updated Sale Status: {detail_resp.json()['data']['status']} (Expected: partially_paid)")

        print("\n=== Validation Complete! ===")

if __name__ == "__main__":
    asyncio.run(validate_sales())
