import asyncio

from app.db.database import get_sessionmaker
from app.db.oauth_state_repo import OAuthStateRepo


async def main():
    Session = get_sessionmaker()
    async with Session() as session:
        repo = OAuthStateRepo(session)

        user_id = 111
        state = await repo.create_state(user_id=user_id, ttl_minutes=10)
        ok1 = await repo.consume_state(user_id=user_id, state=state)
        ok2 = await repo.consume_state(
            user_id=user_id, state=state
        )  # второй раз должен быть False

        print("consume first:", ok1)
        print("consume second:", ok2)


if __name__ == "__main__":
    asyncio.run(main())
