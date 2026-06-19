"""Stage 20.1-B domain service tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.daily_control_service import (
    ActivityEntryService,
    CheckinService,
    DailyControlOverlapError,
    DailyControlValidationError,
    DailyScheduleService,
    TimeBlockService,
)


USER_ID = 123456789
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_daily_control_services_") as tmp:
        db_path = Path(tmp) / "services.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


def _dt(hour: int, minute: int = 0, *, day: int = 19) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=TZ)


async def test_schedule_and_time_blocks() -> None:
    async with _session_ctx() as session:
        schedules = DailyScheduleService(session)
        blocks = TimeBlockService(session)
        schedule = await schedules.create(user_id=USER_ID, usage_date=date(2026, 6, 19))
        duplicate_schedule = await schedules.create(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )
        assert duplicate_schedule.id == schedule.id
        schedule = await schedules.update_status(
            schedule_id=schedule.id, user_id=USER_ID, status="confirmed"
        )
        first = await blocks.create(
            schedule_id=schedule.id,
            user_id=USER_ID,
            start_at=_dt(9),
            end_at=_dt(10),
            title="Deep work",
            category="work",
            block_type="task",
            flexibility="flexible",
            source_type="manual",
        )
        assert schedule.version == 2
        same = await blocks.create(
            schedule_id=schedule.id,
            user_id=USER_ID,
            start_at=_dt(9),
            end_at=_dt(10),
            title="Deep work",
            category="work",
            block_type="task",
            flexibility="flexible",
            source_type="manual",
        )
        assert same.id == first.id
        try:
            await blocks.create(
                schedule_id=schedule.id,
                user_id=USER_ID,
                start_at=_dt(9, 30),
                end_at=_dt(10, 30),
                title="Overlap",
                category="work",
                block_type="task",
                flexibility="flexible",
                source_type="manual",
            )
            raise AssertionError("overlapping time block must fail")
        except DailyControlOverlapError:
            pass
        updated = await blocks.update(
            block_id=first.id, user_id=USER_ID, title="Updated work"
        )
        assert updated.title == "Updated work"
        assert len(await blocks.list(schedule_id=schedule.id, user_id=USER_ID)) == 1
        await blocks.delete(block_id=first.id, user_id=USER_ID)
        assert await blocks.list(schedule_id=schedule.id, user_id=USER_ID) == []


async def test_activity_crud_guards_and_local_date() -> None:
    async with _session_ctx() as session:
        activities = ActivityEntryService(session)
        entry = await activities.create(
            user_id=USER_ID,
            start_at=_dt(23, 30),
            end_at=_dt(0, 30, day=20),
            title="Late work",
            category="work",
            source="manual",
            owner_confirmed=True,
        )
        assert entry.usage_date == date(2026, 6, 19)
        same = await activities.create(
            user_id=USER_ID,
            start_at=_dt(23, 30),
            end_at=_dt(0, 30, day=20),
            title="Late work",
            category="work",
            source="manual",
            owner_confirmed=True,
        )
        assert same.id == entry.id
        assert len(await activities.list_for_date(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )) == 1
        try:
            await activities.create(
                user_id=USER_ID,
                start_at=_dt(23, 45),
                end_at=_dt(0, 45, day=20),
                title="Double count",
                category="work",
                source="manual",
            )
            raise AssertionError("overlapping activity must fail")
        except DailyControlOverlapError:
            pass
        try:
            await activities.update(
                entry_id=entry.id,
                user_id=USER_ID,
                waste_marked_by_owner=True,
                owner_confirmed=False,
            )
            raise AssertionError("unconfirmed waste marker must fail")
        except DailyControlValidationError:
            pass
        updated = await activities.update(
            entry_id=entry.id,
            user_id=USER_ID,
            category="learning",
            waste_marked_by_owner=True,
            owner_confirmed=True,
        )
        assert updated.category == "learning"
        assert updated.waste_marked_by_owner is True
        await activities.delete(entry_id=entry.id, user_id=USER_ID)
        assert await activities.list_for_date(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        ) == []


async def test_checkin_idempotency_and_status() -> None:
    async with _session_ctx() as session:
        checkins = CheckinService(session)
        checkin = await checkins.create(
            user_id=USER_ID,
            window_start=_dt(10),
            window_end=_dt(11),
            prompted_at=_dt(11),
        )
        same = await checkins.create(
            user_id=USER_ID,
            window_start=_dt(10),
            window_end=_dt(11),
            prompted_at=_dt(11),
        )
        assert same.id == checkin.id
        answered = await checkins.update_status(
            checkin_id=checkin.id,
            user_id=USER_ID,
            status="answered",
            response_mode="button",
            answered_at=_dt(11, 5),
        )
        assert answered.status == "answered"
        assert answered.response_mode == "button"


async def test_naive_datetime_rejected() -> None:
    async with _session_ctx() as session:
        activities = ActivityEntryService(session)
        try:
            await activities.create(
                user_id=USER_ID,
                start_at=datetime(2026, 6, 19, 9),
                end_at=datetime(2026, 6, 19, 10),
                title="Unsafe",
                category="work",
                source="manual",
            )
            raise AssertionError("naive datetime must fail")
        except DailyControlValidationError:
            pass


async def main_async() -> None:
    await test_schedule_and_time_blocks()
    await test_activity_crud_guards_and_local_date()
    await test_checkin_idempotency_and_status()
    await test_naive_datetime_rejected()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: Daily Control domain services enforce CRUD and safety guards")


if __name__ == "__main__":
    main()
