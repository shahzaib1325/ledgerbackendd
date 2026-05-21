import asyncio
import sys
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User
from app.core.security import verify_password

async def main():
    email = "admin@smartledger.com"
    passwords = [
        "SecurePass1",
        "AdminPass1!",
        "Password123!",
        "admin",
        "AdminPass1",
        "admin123",
        "admin123!",
    ]
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print("User not found!")
            return
        
        print(f"Testing passwords for {email}...")
        for p in passwords:
            valid = verify_password(p, user.hashed_password)
            if valid:
                print(f"MATCH FOUND: {p}")
                return
        print("No matches found in pre-defined list.")

if __name__ == "__main__":
    asyncio.run(main())
