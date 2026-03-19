from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from app.config import load_config

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    global _engine

    if _engine is None:
        db_url = "sqlite+aiosqlite:///./data/app.db"
        _engine = create_async_engine(db_url, echo=False, future=True)

    return _engine


def get_sessionmaker() -> async_sessionmaker:
    global _sessionmaker

    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)

    return _sessionmaker
