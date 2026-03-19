from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_sessionmaker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    Session = get_sessionmaker()
    async with Session() as session:
        yield session
