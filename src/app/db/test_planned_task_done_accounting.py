from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import ActivityEntry, Base, DailySchedule, Task, TimeBlock
from app.services.task_service import TaskService


USER_ID = 123456789


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_planned_done_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'planned_done.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def _create_task(session, *, title: str = "Family plan") -> Task:
    task = Task(
        title=title,
        planned_at=None,
        duration_min=30,
        status="todo",
        category="family",
        context_status="normal",
        created_at=now_tz(),
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def _create_confirmed_block(session, *, task: Task) -> TimeBlock:
    now = now_tz()
    start_at = now.replace(hour=14, minute=0, second=0, microsecond=0)
    schedule = DailySchedule(
        user_id=USER_ID,
        usage_date=now.date(),
        status="confirmed",
        version=1,
        created_at=now,
        updated_at=now,
        confirmed_at=now,
    )
    session.add(schedule)
    await session.flush()
    block = TimeBlock(
        schedule_id=schedule.id,
        user_id=USER_ID,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
        title=task.title,
        category=task.category,
        block_type="fixed_task",
        flexibility="fixed",
        source_type="task",
        source_id=task.id,
        status="planned",
        created_at=now,
        updated_at=now,
    )
    session.add(block)
    await session.commit()
    await session.refresh(block)
    return block


async def test_done_creates_activity_from_confirmed_time_block() -> None:
    async with _session_ctx() as session:
        task = await _create_task(session)
        block = await _create_confirmed_block(session, task=task)

        done = await TaskService(session).mark_done(task.id, user_id=USER_ID)
        entry = (await session.execute(select(ActivityEntry))).scalar_one()

        assert done is not None and done.status == "done"
        assert entry.user_id == USER_ID
        assert entry.start_at == block.start_at
        assert entry.end_at == block.end_at
        assert entry.title == block.title
        assert entry.category == "family_time"
        assert entry.source == "planned_task"
        assert entry.owner_confirmed is True
        assert entry.waste_marked_by_owner is False


async def test_repeated_done_is_idempotent() -> None:
    async with _session_ctx() as session:
        task = await _create_task(session)
        await _create_confirmed_block(session, task=task)
        service = TaskService(session)

        await service.mark_done(task.id, user_id=USER_ID)
        await service.mark_done(task.id, user_id=USER_ID)

        count = await session.scalar(select(func.count(ActivityEntry.id)))
        assert count == 1


async def test_done_without_confirmed_block_keeps_legacy_behavior() -> None:
    async with _session_ctx() as session:
        task = await _create_task(session, title="Unscheduled task")

        done = await TaskService(session).mark_done(task.id, user_id=USER_ID)
        count = await session.scalar(select(func.count(ActivityEntry.id)))

        assert done is not None and done.status == "done"
        assert count == 0


async def main_async() -> None:
    await test_done_creates_activity_from_confirmed_time_block()
    await test_repeated_done_is_idempotent()
    await test_done_without_confirmed_block_keeps_legacy_behavior()


if __name__ == "__main__":
    asyncio.run(main_async())
    print("PASS: completed planned tasks are accounted once from confirmed blocks")
