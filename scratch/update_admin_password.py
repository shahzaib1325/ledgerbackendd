import asyncio
import sys
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User
from app.core.security import hash_password

async def main():
    email = "admin@smartledger.com"
    new_password = "AdminPass1!"
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print("User not found!")
            return
        
        user.hashed_password = hash_password(new_password)
        await db.commit()
        print(f"Hashed password for {email} successfully updated to '{new_password}'.")

if __name__ == "__main__":
    asyncio.run(main())
