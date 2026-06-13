import asyncio
import os
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.db.models import Base, Task
from app.services.capture_action_service import CaptureActionService


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "capture_actions_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            result = await session.execute(select(Task))
            assert list(result.scalars().all()) == []

            service = CaptureActionService(session)

            later = await service.create_later_from_text("Разобрать идею")
            assert later.status == "later"
            assert later.title == "Разобрать идею"

            boss = await service.create_boss_from_text(
                "Шеф: отправить отчет",
                user_id=123456789,
            )
            assert boss.status == "todo"
            assert boss.category == "work"
            assert boss.title == "Шеф: отправить отчет"

            task_result = await service.create_task_from_text(
                "personal Позвонить маме",
                user_id=123456789,
            )
            assert task_result.local_created is True
            assert task_result.task is not None
            assert task_result.task.title == "Позвонить маме"
            assert task_result.task.category == "personal"

            result = await session.execute(select(Task).order_by(Task.id.asc()))
            tasks = list(result.scalars().all())
            assert [task.status for task in tasks] == ["later", "todo", "todo"]

        await engine.dispose()

    print("PASS: capture actions use temp DB and existing services")


if __name__ == "__main__":
    asyncio.run(main())
