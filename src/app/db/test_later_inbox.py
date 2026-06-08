import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import now_tz
from app.db.models import Base, Task
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
            later_task = Task(
                title="Review passport renewal",
                planned_at=None,
                duration_min=30,
                status="later",
                category="other",
                context_status="normal",
                created_at=now_tz(),
            )
            session.add(later_task)
            await session.commit()
            await session.refresh(later_task)

            assert later_task.status == "later"
            assert later_task.planned_at is None

            result = await session.execute(
                select(Task)
                .where(Task.status == "later")
                .order_by(Task.created_at.asc(), Task.id.asc())
            )
            later_items = list(result.scalars().all())
            assert [item.title for item in later_items] == ["Review passport renewal"]

            timed, floating = await TaskService(session).list_today()
            active_ids = {item.id for item in timed + floating}
            assert later_task.id not in active_ids

        await engine.dispose()

    print("PASS: Later Inbox storage uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
