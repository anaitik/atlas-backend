import asyncio
from app.db.session import connect_db
from app.models.company import Company

async def run():
    await connect_db()
    companies = await Company.find_all().to_list()
    for c in companies:
        print(f"{c.name} | {c.id} | {c.status}")

if __name__ == "__main__":
    asyncio.run(run())
