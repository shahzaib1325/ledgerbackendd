import asyncio
import sys
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User
from app.core.security import hash_password

async def reset_password():
    email = "admin@smartledger.com"
    original_password = "AdminPass1!"
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if user:
            user.hashed_password = hash_password(original_password)
            await db.commit()
            print(f"Password reset for user: {email} succeeded!")
        else:
            print(f"User {email} not found.")

if __name__ == "__main__":
    asyncio.run(reset_password())
