import asyncio
import os
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import now_tz
from app.db.models import Base, DailyPlan, Task
from app.services.daily_plan_service import DailyPlanService
from app.services.task_service import TaskService


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "daily_plan_lifecycle_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            now = now_tz()
            task = Task(
                title="Finish lifecycle",
                planned_at=None,
                duration_min=30,
                status="todo",
                category="work",
                context_status="normal",
                created_at=now,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            assert task.completed_at is None

            task_service = TaskService(session)
            done = await task_service.mark_done(task.id)
            await session.refresh(task)
            first_completed_at = task.completed_at

            assert done is not None
            assert done.status == "done"
            assert done.completed_at is not None
            assert first_completed_at is not None

            done_again = await task_service.mark_done(task.id)
            await session.refresh(task)

            assert done_again is not None
            assert task.completed_at == first_completed_at

            yesterday_done = Task(
                title="Yesterday done",
                planned_at=None,
                duration_min=30,
                status="done",
                category="work",
                context_status="normal",
                created_at=now,
                completed_at=now - timedelta(days=1),
            )
            session.add(yesterday_done)
            await session.commit()

            done_today = await task_service.list_done_for_date(now.date())
            assert [item.title for item in done_today] == ["Finish lifecycle"]

            plan_service = DailyPlanService(session)
            tomorrow = now.date() + timedelta(days=1)
            saved = await plan_service.save_plan(
                plan_date=tomorrow,
                text="Deep work, then family call.",
            )
            read_back = await plan_service.get_plan(tomorrow)
            updated = await plan_service.save_plan(
                plan_date=tomorrow,
                text="Deep work first.",
            )
            plans = (await session.execute(select(DailyPlan))).scalars().all()

            assert saved.source == "telegram_manual"
            assert read_back is not None
            assert read_back.text == "Deep work, then family call."
            assert updated.id == saved.id
            assert updated.text == "Deep work first."
            assert len(plans) == 1

        await engine.dispose()

    print("PASS: DailyPlan lifecycle uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
