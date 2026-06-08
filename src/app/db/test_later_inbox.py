import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.db.models import Base
from app.services.task_service import TaskService


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "later_inbox_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            service = TaskService(session)
            later_task = await service.create_later("Review passport renewal")

            assert later_task.status == "later"
            assert later_task.planned_at is None
            assert later_task.duration_min == 30
            assert later_task.category == "other"

            later_items = await service.list_later()
            assert [item.title for item in later_items] == ["Review passport renewal"]

            timed, floating = await service.list_today()
            active_ids = {item.id for item in timed + floating}
            assert later_task.id not in active_ids

        await engine.dispose()

    print("PASS: Later Inbox storage uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
