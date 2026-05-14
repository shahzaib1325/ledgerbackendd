import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"

async def test_inventory():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        print("=== 0. Login to get token ===")
        login_payload = {"username": "testadmin_final", "password": "Password123!"}
        resp = await client.post("/auth/login", json=login_payload)
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} - {resp.text}")
            return
        token = resp.json()["data"]["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        print("\n=== 1. Testing Units API ===")
        # POST /inventory/units
        unit_payload = {"name": "Test Unit", "abbreviation": "TU"}
        print(f"Creating unit: {unit_payload}")
        response = await client.post("/inventory/units", json=unit_payload, headers=headers)
        
        if response.status_code not in (200, 201):
            print(f"Failed to create unit: {response.status_code} - {response.text}")
            return
            
        unit_data = response.json()
        unit_id = unit_data.get("data", {}).get("id") or unit_data.get("id")
        print(f"Success! Created Unit ID: {unit_id}")

        print("\n=== 2. Testing Categories API ===")
        # POST /inventory/categories
        cat_payload = {"name": "Test Category"}
        print(f"Creating category: {cat_payload}")
        response = await client.post("/inventory/categories", json=cat_payload, headers=headers)
        if response.status_code not in (200, 201):
            print(f"Failed to create category: {response.status_code} - {response.text}")
            return
        
        cat_data = response.json()
        category_id = cat_data.get("data", {}).get("id") or cat_data.get("id")
        print(f"Success! Created Category ID: {category_id}")

        print("\n=== 3. Testing Items API ===")
        # POST /inventory/items
        item_payload = {
            "name": "Test Item",
            "sku": "ITEM-001",
            "unit_id": unit_id,
            "category_id": category_id,
            "item_type": "product"
        }
        print(f"Creating item: {item_payload}")
        response = await client.post("/inventory/items", json=item_payload, headers=headers)
        if response.status_code not in (200, 201):
            print(f"Failed to create item: {response.status_code} - {response.text}")
            return
            
        item_data = response.json()
        item_id = item_data.get("data", {}).get("id") or item_data.get("id")
        print(f"Success! Created Item ID: {item_id}")

        print("\n=== 4. Testing End-to-End Item Retrieval ===")
        response = await client.get(f"/inventory/items/{item_id}", headers=headers)
        print(f"Item Details: {response.status_code} -> {response.json().get('data', response.json())}")
        
        print("\n=== All Tests Passed Successfully ===")

if __name__ == "__main__":
    asyncio.run(test_inventory())
