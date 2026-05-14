import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.auth import User

async def list_users():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
        
        if users:
            print(f"Total Users: {len(users)}")
            for u in users:
                print(f"ID: {u.id} | Email: {u.email} | Username: {u.username} | Role: {u.role.value}")
        else:
            print("No users found in database.")

if __name__ == "__main__":
    asyncio.run(list_users())
