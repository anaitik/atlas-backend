import asyncio
from app.db.session import connect_db
from app.models.user import User

async def main():
    await connect_db()
    u = await User.find_one({"email": "test@test.com"})
    if u:
        u.status = "active"
        u.role = "system_admin"
        await u.save()
        print("User approved and granted system_admin")
    else:
        print("User not found")

if __name__ == "__main__":
    asyncio.run(main())
