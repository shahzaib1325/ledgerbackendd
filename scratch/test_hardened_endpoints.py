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
    original_password = "AdminPass1!"
    new_password = "AdminNewPass2!"
    common_password = "password1"

    print("=== Testing Hardened Auth & Session Invalidation Endpoints ===")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login to get original token pair
        print("\n1. Logging in with original password to get session 1...")
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": email,
            "password": original_password
        })
        print(f"Login status: {login_resp.status_code}")
        login_data = login_resp.json()["data"]
        access_token_1 = login_data["tokens"]["access_token"]
        refresh_token_1 = login_data["tokens"]["refresh_token"]
        headers_1 = {"Authorization": f"Bearer {access_token_1}"}

        # 2. Test common password validation rejection
        print("\n2. Testing change-password with common password...")
        change_common_resp = await client.post("/api/v1/auth/change-password", headers=headers_1, json={
            "current_password": original_password,
            "new_password": common_password
        })
        print(f"Common password change status: {change_common_resp.status_code}")
        print(f"Response: {change_common_resp.text}")
        assert change_common_resp.status_code == 422, "Should reject common password with 422"
        resp_json = change_common_resp.json()
        assert resp_json["error"]["code"] == "VALIDATION_ERROR", "Error code should be VALIDATION_ERROR"
        assert resp_json["error"]["field"] == "new_password", "Error field should map to new_password"
        print("-> Common password rejected with correct field validation mapping!")

        # 3. Perform successful password change
        print("\n3. Performing successful password change to revoke session 1...")
        change_ok_resp = await client.post("/api/v1/auth/change-password", headers=headers_1, json={
            "current_password": original_password,
            "new_password": new_password
        })
        print(f"Change password status: {change_ok_resp.status_code}")
        assert change_ok_resp.status_code == 200, "Password change should succeed"

        # 4. Verify original access token is now invalid (multi-session invalidation)
        print("\n4. Verifying original access token is now invalid...")
        me_resp_1 = await client.get("/api/v1/auth/me", headers=headers_1)
        print(f"Me status with old access token: {me_resp_1.status_code}")
        print(f"Response: {me_resp_1.text}")
        assert me_resp_1.status_code == 401, "Old access token should be revoked"
        assert me_resp_1.json()["error"]["code"] == "TOKEN_EXPIRED", "Error code should be TOKEN_EXPIRED"
        print("-> Old access token successfully invalidated!")

        # 5. Verify original refresh token is now invalid (multi-session invalidation)
        print("\n5. Verifying original refresh token is now invalid...")
        refresh_resp_1 = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token_1
        })
        print(f"Refresh status with old refresh token: {refresh_resp_1.status_code}")
        print(f"Response: {refresh_resp_1.text}")
        assert refresh_resp_1.status_code == 401, "Old refresh token should be revoked"
        assert refresh_resp_1.json()["error"]["code"] == "TOKEN_INVALID", "Error code should be TOKEN_INVALID"
        print("-> Old refresh token successfully invalidated!")

        # 6. Login with new password to get session 2
        print("\n6. Logging in with new password to get session 2...")
        login_resp_2 = await client.post("/api/v1/auth/login", json={
            "email": email,
            "password": new_password
        })
        print(f"Login status: {login_resp_2.status_code}")
        login_data_2 = login_resp_2.json()["data"]
        access_token_2 = login_data_2["tokens"]["access_token"]
        refresh_token_2 = login_data_2["tokens"]["refresh_token"]
        headers_2 = {"Authorization": f"Bearer {access_token_2}"}

        # Verify profile can be fetched with active session 2
        me_resp_2 = await client.get("/api/v1/auth/me", headers=headers_2)
        print(f"Me status with new access token: {me_resp_2.status_code}")
        assert me_resp_2.status_code == 200, "New access token should be valid"

        # 7. Perform secure logout revoking both access & refresh tokens
        print("\n7. Performing secure logout of session 2...")
        logout_resp = await client.post("/api/v1/auth/logout", headers=headers_2, json={
            "refresh_token": refresh_token_2
        })
        print(f"Logout status: {logout_resp.status_code}")
        assert logout_resp.status_code == 200, "Logout should succeed"

        # Verify access token is blacklisted
        me_resp_after_logout = await client.get("/api/v1/auth/me", headers=headers_2)
        print(f"Me status after logout: {me_resp_after_logout.status_code}")
        assert me_resp_after_logout.status_code == 401, "Access token should be blacklisted"

        # Verify refresh token is blacklisted
        refresh_resp_after_logout = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token_2
        })
        print(f"Refresh status after logout: {refresh_resp_after_logout.status_code}")
        assert refresh_resp_after_logout.status_code == 401, "Refresh token should be blacklisted"
        print("-> Both access and refresh tokens successfully blacklisted during logout!")

        # 8. Restore original password for environmental safety
        print("\n8. Restoring original password...")
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            db_user = result.scalar_one_or_none()
            if db_user:
                from app.core.security import hash_password
                db_user.hashed_password = hash_password(original_password)
                await db.commit()
                print("Original password successfully restored in DB.")
            else:
                print("Failed to find user to restore password.")

if __name__ == "__main__":
    asyncio.run(main())
