import asyncio
import sys
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from app.main import app
from app.core.security import verify_password
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User

async def main():
    email = "admin@smartledger.com"
    current_password = "AdminPass1!"
    new_password = "AdminNewPass2!"

    print("=== Testing Self-User Endpoints (GET /me, POST /change-password) ===")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login to get tokens
        print("\n1. Logging in with original password...")
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": email,
            "password": current_password
        })
        print(f"Login status: {login_resp.status_code}")
        if login_resp.status_code != 200:
            print(f"Error login: {login_resp.text}")
            return
        
        login_data = login_resp.json()["data"]
        access_token = login_data["tokens"]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 2. Get Profile (/me)
        print("\n2. Getting current profile (/auth/me)...")
        me_resp = await client.get("/api/v1/auth/me", headers=headers)
        print(f"Get Profile status: {me_resp.status_code}")
        print(f"Profile Data: {me_resp.json()}")

        # 3. Change Password - Negative Test (same password)
        print("\n3. Testing change-password with same password...")
        change_same_resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": current_password,
            "new_password": current_password
        })
        print(f"Change password status (same): {change_same_resp.status_code}")
        print(f"Response (same): {change_same_resp.text}")

        # 4. Change Password - Negative Test (wrong current password)
        print("\n4. Testing change-password with wrong current password...")
        change_wrong_resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": "WrongPassword123!",
            "new_password": new_password
        })
        print(f"Change password status (wrong current): {change_wrong_resp.status_code}")
        print(f"Response (wrong current): {change_wrong_resp.text}")

        # 5. Change Password - Negative Test (weak password)
        print("\n5. Testing change-password with weak new password...")
        change_weak_resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": current_password,
            "new_password": "weak"
        })
        print(f"Change password status (weak): {change_weak_resp.status_code}")
        print(f"Response (weak): {change_weak_resp.text}")

        # 6. Change Password - Success Test
        print("\n6. Testing successful change-password...")
        change_ok_resp = await client.post("/api/v1/auth/change-password", headers=headers, json={
            "current_password": current_password,
            "new_password": new_password
        })
        print(f"Change password status (success): {change_ok_resp.status_code}")
        print(f"Response (success): {change_ok_resp.text}")

        # Verify password in DB has changed and is correct
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            db_user = result.scalar_one_or_none()
            is_valid_new = verify_password(new_password, db_user.hashed_password) if db_user else False
            print(f"DB verification - New password valid: {is_valid_new}")

        # 7. Restore Password
        print("\n7. Restoring original password for safety...")
        # Since password changed, we need a new login or we can update directly in DB
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            db_user = result.scalar_one_or_none()
            if db_user:
                from app.core.security import hash_password
                db_user.hashed_password = hash_password(current_password)
                await db.commit()
                print("Original password successfully restored in DB.")
            else:
                print("Failed to find user to restore password.")

if __name__ == "__main__":
    asyncio.run(main())
