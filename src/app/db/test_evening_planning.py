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
from app.db.models import AlertQueue, Base, Task
from app.scheduler.jobs import _ensure_quran_followup_alert
from app.services.crisis_stack_service import CrisisStackService
from app.services.evening_planning_service import (
    EveningPlanningInput,
    build_evening_planning_message,
)
from app.services.task_service import TaskService


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "evening_planning_test.db"
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
            today_at = now.replace(hour=17, minute=0, second=0, microsecond=0)
            tomorrow_at = (now + timedelta(days=1)).replace(
                hour=10,
                minute=0,
                second=0,
                microsecond=0,
            )
            session.add_all(
                [
                    Task(
                        title="Finish report",
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
                        title="Call supplier",
                        planned_at=None,
                        duration_min=30,
                        status="later",
                        category="other",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Tomorrow planning call",
                        planned_at=tomorrow_at,
                        duration_min=45,
                        status="todo",
                        category="work",
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
                        title="Hidden cancelled tomorrow",
                        planned_at=tomorrow_at,
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
            today_titles = [task.title for task in timed + floating]

            assert today_titles == ["Finish report", "Срочно проверить договор"]
            assert "Hidden done task" not in today_titles

            later_items = await task_service.list_later(limit=5)
            assert [item.title for item in later_items] == ["Call supplier"]

            tomorrow_tasks = await task_service.list_tomorrow()
            tomorrow_titles = [task.title for task in tomorrow_tasks]
            assert tomorrow_titles == ["Tomorrow planning call"]

            focus_task = CrisisStackService.select_focus_task(timed + floating)
            assert focus_task is not None
            assert focus_task.title == "Срочно проверить договор"
            assert not CrisisStackService.is_crisis(timed + floating)

            message = build_evening_planning_message(
                EveningPlanningInput(
                    unfinished_tasks=timed + floating,
                    later_items=later_items,
                    tomorrow_tasks=tomorrow_tasks,
                    prayer_lines=["• Fajr: done"],
                    quran_lines=["• Quran: review"],
                    health_lines=["• Hydration: ok"],
                    google_tomorrow_lines=["• 10:00 — Standup"],
                )
            )

            assert "Вечерний план" in message
            assert "Закрытые сегодня пока не отслеживаются." in message
            assert "Finish report" in message
            assert "Срочно проверить договор" in message
            assert "Call supplier" in message
            assert "Tomorrow planning call" in message
            assert "Standup" in message
            assert "Что главное завтра?" in message

            first_alert_id = await _ensure_quran_followup_alert(
                session=session,
                chat_id=123,
                summary_text="Read 2 pages",
            )
            second_alert_id = await _ensure_quran_followup_alert(
                session=session,
                chat_id=123,
                summary_text="Read 3 pages",
            )

            assert first_alert_id == second_alert_id

            result = await session.execute(
                select(AlertQueue).where(AlertQueue.alert_type == "quran_followup")
            )
            alerts = list(result.scalars().all())
            assert len(alerts) == 1
            assert alerts[0].status == "pending"

        await engine.dispose()

    print("PASS: Evening planning smoke test uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
