import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.db.models import Base
from app.db.oauth_state_repo import OAuthStateRepo


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "oauth_state_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            repo = OAuthStateRepo(session)

            user_id = 111
            code_verifier = "test-code-verifier"
            state = await repo.create_state(
                user_id=user_id,
                code_verifier=code_verifier,
                ttl_minutes=10,
            )
            ok1 = await repo.consume_state(user_id=user_id, state=state)
            ok2 = await repo.consume_state(user_id=user_id, state=state)

            assert ok1 is True
            assert ok2 is False

        await engine.dispose()

    print("PASS: OAuthStateRepo uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
