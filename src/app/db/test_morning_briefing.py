import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import APP_TZ, now_tz
from app.db.models import Base, Task
from app.services.crisis_stack_service import CrisisStackService
from app.services.task_service import TaskService


@dataclass(slots=True)
class FakeGoogleEvent:
    summary: str
    start_at: object | None = None
    all_day: bool = False


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "morning_briefing_test.db"
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
            today_at = now.replace(hour=10, minute=0, second=0, microsecond=0)
            google_at = now.replace(hour=9, minute=30, second=0, microsecond=0)

            session.add_all(
                [
                    Task(
                        title="Prepare standup",
                        planned_at=today_at,
                        duration_min=30,
                        status="todo",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Срочно проверить договор",
                        planned_at=None,
                        duration_min=30,
                        status="todo",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Inbox idea",
                        planned_at=None,
                        duration_min=30,
                        status="later",
                        category="other",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Hidden done task",
                        planned_at=today_at,
                        duration_min=30,
                        status="done",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Hidden cancelled task",
                        planned_at=today_at,
                        duration_min=30,
                        status="cancelled",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                ]
            )
            await session.commit()

            task_service = TaskService(session)
            timed, floating = await task_service.list_today()
            active_tasks = timed + floating
            active_titles = [task.title for task in active_tasks]

            assert active_titles == [
                "Prepare standup",
                "Срочно проверить договор",
            ]
            assert "Hidden done task" not in active_titles
            assert "Hidden cancelled task" not in active_titles

            later_items = await task_service.list_later(limit=5)
            assert len(later_items) == 1
            assert later_items[0].title == "Inbox idea"

            focus_task = CrisisStackService.select_focus_task(active_tasks)
            assert focus_task is not None
            assert focus_task.title == "Срочно проверить договор"
            assert not CrisisStackService.is_crisis(active_tasks)

            fake_google_events = [
                FakeGoogleEvent(summary="Daily sync", start_at=google_at),
                FakeGoogleEvent(summary="Conference day", all_day=True),
            ]
            google_summaries = [event.summary for event in fake_google_events]
            assert google_summaries == ["Daily sync", "Conference day"]
            assert fake_google_events[0].start_at.astimezone(APP_TZ).strftime("%H:%M") == "09:30"

            morning_words = [
                "Утро. План на сегодня",
                "Фокус",
                "Сегодня",
                "Google Calendar",
                "На потом",
            ]
            assert all(morning_words)

        await engine.dispose()

    print("PASS: Morning briefing smoke test uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
