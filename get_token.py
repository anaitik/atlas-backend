import asyncio
from datetime import timedelta
from app.db.session import connect_db
from app.models.user import User
from app.core.security import create_jwt_token
from app.config import get_settings

async def run():
    await connect_db()
    user = await User.find_one({"email": "test@test.com"})
    if user:
        token = create_jwt_token(
            data={"user_id": user.id, "role": user.role, "company_id": user.company_id},
            expires_delta=timedelta(minutes=60)
        )
        print(token)
    else:
        print("User not found")

if __name__ == "__main__":
    asyncio.run(run())
