import asyncio

from app.db.database import get_engine
from app.db.models import Base  # metadata
from app.db.models import OAuthState  # noqa: F401 (важно, чтобы модель импортнулась)


async def main() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(main())
