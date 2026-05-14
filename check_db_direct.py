import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User
from app.core.security import verify_password

async def check_user():
    email = "admin@example.com"
    password = "SecurePass1"
    
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if user:
            print(f"USER_EXISTS: True")
            print(f"ROLE: {user.role.value}")
            is_valid = verify_password(password, user.hashed_password)
            print(f"PASSWORD_VALID: {is_valid}")
        else:
            print(f"USER_EXISTS: False")

if __name__ == "__main__":
    asyncio.run(check_user())
