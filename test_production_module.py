import asyncio
import httpx
from datetime import datetime, date

BASE_URL = "http://127.0.0.1:8000/api/v1/"

async def validate_production_module():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        print("=== 0. Login ===")
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} - {resp.text}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        timestamp = int(datetime.now().timestamp())

        print("\n=== 1. Setup Inventory ===")
        # Create Unit
        unit_payload = {"name": f"Kilogram {timestamp}", "abbreviation": f"k{str(timestamp)[-5:]}"}
        resp = await client.post("inventory/units", json=unit_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Create unit failed: {resp.status_code} - {resp.text}")
            return
        unit_id = resp.json()["data"]["id"]

        # Create Raw Material Item
        raw_payload = {
            "name": f"Wood {timestamp}",
            "unit_id": unit_id,
            "item_type": "purchased",
            "purchase_price": 50.0
        }
        resp = await client.post("inventory/items", json=raw_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Create raw material failed: {resp.status_code} - {resp.text}")
            return
        raw_id = resp.json()["data"]["id"]

        # Adjust Stock for Raw Material
        adj_payload = {"item_id": raw_id, "quantity": 100.0, "note": "Initial stock for testing"}
        resp = await client.post(f"inventory/items/{raw_id}/adjust", json=adj_payload, headers=headers)
        
        # Create Finished Good Item
        fg_payload = {
            "name": f"Table {timestamp}",
            "unit_id": unit_id,
            "item_type": "produced",
            "sale_price": 500.0
        }
        resp = await client.post("inventory/items", json=fg_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Create finished good failed: {resp.status_code} - {resp.text}")
            return
        fg_id = resp.json()["data"]["id"]

        print(f"Inventory setup complete. Raw: {raw_id}, FG: {fg_id}")

        print("\n=== 2. Create Production Order ===")
        order_payload = {
            "order_no": f"PRD-{timestamp}",
            "product_item_id": fg_id,
            "quantity_to_produce": 10.0,
            "start_date": str(date.today()),
            "raw_materials": [
                {
                    "item_id": raw_id,
                    "unit_id": unit_id,
                    "required_quantity": 20.0,
                    "unit_cost": 50.0
                }
            ],
            "labor": [
                {
                    "description": "Assembly",
                    "hours": 5.0,
                    "rate_per_hour": 100.0
                }
            ],
            "costs": [
                {
                    "cost_type": "Electricity",
                    "amount": 200.0
                }
            ]
        }
        resp = await client.post("production", json=order_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Create production order failed: {resp.status_code} - {resp.text}")
            return
        order = resp.json()["data"]
        order_id = order["id"]
        print(f"Production order created successfully: ID {order_id}, Status: {order['status']}, Total Cost: {order['total_cost']}")

        print("\n=== 3. Start Production Order ===")
        resp = await client.post(f"production/{order_id}/start", headers=headers)
        if resp.status_code != 200:
            print(f"Start production order failed: {resp.status_code} - {resp.text}")
            return
        print(f"Production order started successfully. Status: {resp.json()['data']['status']}")

        print("\n=== 4. Add Additional Labor ===")
        labor_payload = {
            "description": "Painting",
            "hours": 2.0,
            "rate_per_hour": 150.0
        }
        resp = await client.post(f"production/{order_id}/labor", json=labor_payload, headers=headers)
        if resp.status_code != 201:
            print(f"Add labor failed: {resp.status_code} - {resp.text}")
        else:
            print("Additional labor added successfully.")

        print("\n=== 5. Complete Production Order ===")
        output_payload = {
            "quantity_produced": 10.0
        }
        resp = await client.post(f"production/{order_id}/complete", json=output_payload, headers=headers)
        if resp.status_code != 200:
            print(f"Complete production order failed: {resp.status_code} - {resp.text}")
            return
        order = resp.json()["data"]
        print(f"Production order completed successfully. Status: {order['status']}, Final Total Cost: {order['total_cost']}")

        print("\n=== 6. Verify Stock Movements ===")
        # Check raw material stock
        resp = await client.get(f"inventory/items/{raw_id}", headers=headers)
        raw_stock = resp.json()["data"]["current_stock"]
        
        # Check finished good stock
        resp = await client.get(f"inventory/items/{fg_id}", headers=headers)
        fg_stock = resp.json()["data"]["current_stock"]
        
        print(f"Raw Material Stock: {raw_stock} (Expected 80.0)")
        print(f"Finished Good Stock: {fg_stock} (Expected 10.0)")

        print("\n=== Validation Complete! ===")

if __name__ == "__main__":
    asyncio.run(validate_production_module())
