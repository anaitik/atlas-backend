import asyncio
from app.db.session import connect_db
from app.models.user import User
from app.core.security import get_password_hash, verify_password

async def run():
    await connect_db()
    user = await User.find_one({"email": "test@test.com"})
    if user:
        password = "password123"
        hashed = get_password_hash(password)
        user.hashed_password = hashed
        await user.save()
        print(f"Password reset for {user.email}")
        print(f"New Hash: {hashed}")
        
        # Verify immediately
        match = verify_password(password, hashed)
        print(f"Verified: {match}")
    else:
        print("User not found")

if __name__ == "__main__":
    asyncio.run(run())
