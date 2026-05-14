import asyncio
import sys
from sqlalchemy import update
from app.core.database import async_engine
from app.models.auth import User
from app.models.enums import UserRole

async def promote(username: str):
    async with async_engine.begin() as conn:
        await conn.execute(
            update(User)
            .where(User.username == username)
            .values(role=UserRole.admin)
        )
    print(f"Promoted {username} to admin.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python promote_user.py <username>")
        sys.exit(1)
    username = sys.argv[1]
    asyncio.run(promote(username))
