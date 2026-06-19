"""Stage 20.1-C interval accounting tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.daily_control_accounting_service import (
    DailyControlAccountingService,
)
from app.services.daily_control_service import (
    ActivityEntryService,
    DailyScheduleService,
    TimeBlockService,
)


USER_ID = 123456789
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_daily_control_accounting_") as tmp:
        db_path = Path(tmp) / "accounting.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=TZ)


async def test_totals_plan_vs_fact_and_safe_categories() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )
        await TimeBlockService(session).create(
            schedule_id=schedule.id,
            user_id=USER_ID,
            start_at=_dt(19, 9),
            end_at=_dt(19, 10),
            title="Planned work",
            category="work",
            block_type="task",
            flexibility="flexible",
            source_type="manual",
        )
        activities = ActivityEntryService(session)
        await activities.create(
            user_id=USER_ID,
            start_at=_dt(19, 9, 15),
            end_at=_dt(19, 10, 15),
            title="Actual work",
            category="work",
            source="manual",
            owner_confirmed=True,
        )
        await activities.create(
            user_id=USER_ID,
            start_at=_dt(19, 12),
            end_at=_dt(19, 12, 30),
            title="No recollection",
            category="unaccounted",
            source="checkin",
            owner_confirmed=True,
        )
        await activities.create(
            user_id=USER_ID,
            start_at=_dt(19, 13),
            end_at=_dt(19, 13, 20),
            title="Owner marked",
            category="rest",
            source="manual",
            owner_confirmed=True,
            waste_marked_by_owner=True,
        )
        await activities.create(
            user_id=USER_ID,
            start_at=_dt(19, 23, 30),
            end_at=_dt(20, 0, 30),
            title="Cross midnight",
            category="work",
            source="manual",
            owner_confirmed=True,
        )

        summary = await DailyControlAccountingService(session).summarize(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )
        assert summary.planned_minutes == 60.0
        assert summary.actual_minutes == 140.0
        assert summary.plan_variance_minutes == 80.0
        assert summary.useful_outside_plan_minutes == 45.0
        assert summary.unaccounted_minutes == 30.0
        assert summary.owner_marked_waste_minutes == 20.0
        assert summary.no_data_minutes == 1300.0
        assert summary.category_minutes == {
            "work": 90.0,
            "unaccounted": 30.0,
            "rest": 20.0,
        }


async def test_cross_midnight_is_split_without_double_count() -> None:
    async with _session_ctx() as session:
        await ActivityEntryService(session).create(
            user_id=USER_ID,
            start_at=_dt(19, 23, 30),
            end_at=_dt(20, 0, 30),
            title="Cross midnight",
            category="work",
            source="manual",
            owner_confirmed=True,
        )
        accounting = DailyControlAccountingService(session)
        first = await accounting.summarize(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )
        second = await accounting.summarize(
            user_id=USER_ID, usage_date=date(2026, 6, 20)
        )
        assert first.actual_minutes == 30.0
        assert second.actual_minutes == 30.0
        assert first.actual_minutes + second.actual_minutes == 60.0
        assert first.no_data_minutes == 1410.0
        assert second.no_data_minutes == 1410.0


async def test_empty_day_remains_no_data_not_waste() -> None:
    async with _session_ctx() as session:
        summary = await DailyControlAccountingService(session).summarize(
            user_id=USER_ID, usage_date=date(2026, 6, 19)
        )
        assert summary.actual_minutes == 0.0
        assert summary.unaccounted_minutes == 0.0
        assert summary.owner_marked_waste_minutes == 0.0
        assert summary.no_data_minutes == 1440.0


async def main_async() -> None:
    await test_totals_plan_vs_fact_and_safe_categories()
    await test_cross_midnight_is_split_without_double_count()
    await test_empty_day_remains_no_data_not_waste()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: Daily Control interval accounting is local-day and safety aware")


if __name__ == "__main__":
    main()
