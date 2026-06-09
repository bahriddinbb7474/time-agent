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
from app.services.crisis_stack_service import CrisisStackService
from app.services.task_service import TaskService


async def main():
    assert CrisisStackService.is_urgent_text("🔥 Проверить платеж")
    assert CrisisStackService.is_urgent_text("Срочно ответить клиенту")
    assert CrisisStackService.is_urgent_text("Шеф срочно: отчет")
    assert not CrisisStackService.is_urgent_text("Плановая прогулка")

    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "focus_crisis_test.db"
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
            session.add_all(
                [
                    Task(
                        title="Обычная floating задача",
                        planned_at=None,
                        duration_min=30,
                        status="todo",
                        category="personal",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Срочно отправить договор",
                        planned_at=None,
                        duration_min=30,
                        status="todo",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="🔥 Закрыть платеж",
                        planned_at=None,
                        duration_min=30,
                        status="todo",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Срочно скрытая done задача",
                        planned_at=None,
                        duration_min=30,
                        status="done",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Срочно скрытая later задача",
                        planned_at=None,
                        duration_min=30,
                        status="later",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                    Task(
                        title="Срочно скрытая cancelled задача",
                        planned_at=None,
                        duration_min=30,
                        status="cancelled",
                        category="work",
                        context_status="normal",
                        created_at=now,
                    ),
                ]
            )
            await session.commit()

            _timed, floating = await TaskService(session).list_today()
            floating_titles = [task.title for task in floating]

            assert "Срочно отправить договор" in floating_titles
            assert "🔥 Закрыть платеж" in floating_titles
            assert "Срочно скрытая done задача" not in floating_titles
            assert "Срочно скрытая later задача" not in floating_titles
            assert "Срочно скрытая cancelled задача" not in floating_titles
            assert floating_titles[0] == "Срочно отправить договор"

            focus_task = CrisisStackService.select_focus_task(floating)
            assert focus_task is not None
            assert focus_task.title == "Срочно отправить договор"

            urgent_count = sum(
                1
                for task in floating
                if CrisisStackService.is_urgent_text(task.title)
            )
            assert urgent_count == 2
            assert CrisisStackService.is_crisis(floating)
            assert not CrisisStackService.is_crisis([floating[0]])

            active_candidates = await TaskService(session).list_active_focus_candidates()
            active_titles = [task.title for task in active_candidates]
            assert "Срочно отправить договор" in active_titles
            assert "🔥 Закрыть платеж" in active_titles
            assert "Срочно скрытая done задача" not in active_titles
            assert "Срочно скрытая later задача" not in active_titles
            assert "Срочно скрытая cancelled задача" not in active_titles

        await engine.dispose()

    print("PASS: Focus/crisis tests use isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
