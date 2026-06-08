import asyncio
import os
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import now_tz
from app.db.models import Base, Task
from app.services.task_service import TaskService


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

            service = TaskService(session)
            missing = await service.mark_done(9999)
            done = await service.mark_done(task.id)
            done_again = await service.mark_done(task.id)

            assert missing is None
            assert done is not None
            assert done.status == "done"
            assert done_again is not None
            assert done_again.status == "done"
            await session.refresh(task)
            assert task.status == "done"

            planned_at = now_tz().replace(hour=12, minute=0, second=0, microsecond=0)
            session.add_all(
                [
                    Task(
                        title="Visible timed task",
                        planned_at=planned_at,
                        duration_min=30,
                        status="todo",
                        category="personal",
                        context_status="normal",
                        created_at=now_tz(),
                    ),
                    Task(
                        title="Hidden done timed task",
                        planned_at=planned_at + timedelta(hours=1),
                        duration_min=30,
                        status="done",
                        category="personal",
                        context_status="normal",
                        created_at=now_tz(),
                    ),
                    Task(
                        title="Hidden cancelled timed task",
                        planned_at=planned_at + timedelta(hours=2),
                        duration_min=30,
                        status="cancelled",
                        category="personal",
                        context_status="normal",
                        created_at=now_tz(),
                    ),
                ]
            )
            await session.commit()

            timed, _floating = await service.list_today()
            timed_titles = [item.title for item in timed]

            assert "Visible timed task" in timed_titles
            assert "Hidden done timed task" not in timed_titles
            assert "Hidden cancelled timed task" not in timed_titles

        await engine.dispose()

    print("PASS: Task status update uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
