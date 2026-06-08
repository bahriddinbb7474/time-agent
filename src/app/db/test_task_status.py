import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import now_tz
from app.db.models import Base, Task


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "task_status_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            task = Task(
                title="Test task",
                planned_at=None,
                duration_min=30,
                status="todo",
                category="personal",
                context_status="normal",
                created_at=now_tz(),
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            task.status = "done"
            await session.commit()
            await session.refresh(task)

            assert task.status == "done"

        await engine.dispose()

    print("PASS: Task status update uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
