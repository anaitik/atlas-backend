import asyncio
from app.db.session import connect_db
from app.models.user import User
from app.core.security import get_password_hash

async def run():
    await connect_db()
    user = await User.find_one({"email": "test@test.com"})
    if user:
        user.hashed_password = get_password_hash("password123")
        user.status = "active"
        await user.save()
        print("Password updated for test@test.com to 'password123'")
    else:
        print("User test@test.com not found")

if __name__ == "__main__":
    asyncio.run(run())
