import asyncio
from app.db.session import connect_db
from app.models.user import User

async def run():
    await connect_db()
    users = await User.find_all().to_list()
    for u in users:
        print(f"{u.email} | {u.role}")

if __name__ == "__main__":
    asyncio.run(run())
