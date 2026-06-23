"""Stage 20.4-A check-in policy tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, Checkin
from app.services.checkin_policy_service import CheckinPolicyService
from app.services.daily_control_service import (
    ActivityEntryService,
    CheckinService,
    DailyScheduleService,
    TimeBlockService,
)


USER_ID = 123456789
DAY = date(2026, 6, 21)
TZ = timezone(timedelta(hours=5))


def _overlaps(row, start: datetime, end: datetime) -> bool:
    row_start = row.window_start.replace(tzinfo=TZ)
    row_end = row.window_end.replace(tzinfo=TZ)
    return row_start < end and row_end > start


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_checkin_policy_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'policy.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_no_confirmed_schedule_means_no_checkins() -> None:
    async with _session_ctx() as session:
        assert await CheckinPolicyService(session).plan_for_date(
            user_id=USER_ID, usage_date=DAY
        ) == []


async def test_policy_is_idempotent_and_suppresses_protected_windows() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=DAY, status="confirmed"
        )
        blocks = TimeBlockService(session)
        for start, end, kind in ((0, 6, "sleep"), (12, 13, "prayer")):
            await blocks.create(
                schedule_id=schedule.id, user_id=USER_ID,
                start_at=datetime(2026, 6, 21, start, tzinfo=TZ),
                end_at=datetime(2026, 6, 21, end, tzinfo=TZ),
                title=kind.title(), category=kind, block_type=kind,
                flexibility="protected", source_type="test",
            )
        service = CheckinPolicyService(session)
        first = await service.plan_for_date(user_id=USER_ID, usage_date=DAY)
        second = await service.plan_for_date(user_id=USER_ID, usage_date=DAY)
        assert len(first) == 9
        assert [row.id for row in second] == [row.id for row in first]
        assert all(row.schedule_id == schedule.id for row in first)
        assert all(row.schedule_version == schedule.version for row in first)
        assert all(row.usage_date == DAY for row in first)
        assert all(row.status == "pending" for row in first)
        assert all(
            not _overlaps(
                row,
                datetime(2026, 6, 21, 0, tzinfo=TZ),
                datetime(2026, 6, 21, 6, tzinfo=TZ),
            )
            for row in first
        )
        assert all(
            not _overlaps(
                row,
                datetime(2026, 6, 21, 12, tzinfo=TZ),
                datetime(2026, 6, 21, 13, tzinfo=TZ),
            )
            for row in first
        )


async def test_120_minute_interval() -> None:
    async with _session_ctx() as session:
        await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=DAY, status="confirmed"
        )
        rows = await CheckinPolicyService(session).plan_for_date(
            user_id=USER_ID, usage_date=DAY, interval_minutes=120
        )
        assert len(rows) == 12


async def test_confirmed_activity_and_unknown_are_not_prompted_again() -> None:
    async with _session_ctx() as session:
        await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=DAY, status="confirmed"
        )
        await ActivityEntryService(session).create(
            user_id=USER_ID,
            start_at=datetime(2026, 6, 21, 8, tzinfo=TZ),
            end_at=datetime(2026, 6, 21, 10, tzinfo=TZ),
            title="Confirmed work",
            category="work",
            source="test",
            owner_confirmed=True,
        )
        await CheckinService(session).create(
            user_id=USER_ID,
            usage_date=DAY,
            window_start=datetime(2026, 6, 21, 12, tzinfo=TZ),
            window_end=datetime(2026, 6, 21, 14, tzinfo=TZ),
            prompted_at=datetime(2026, 6, 21, 14, tzinfo=TZ),
            status="answered",
            response_mode="unknown",
        )
        await CheckinService(session).create(
            user_id=USER_ID,
            usage_date=DAY,
            window_start=datetime(2026, 6, 21, 16, tzinfo=TZ),
            window_end=datetime(2026, 6, 21, 18, tzinfo=TZ),
            prompted_at=datetime(2026, 6, 21, 18, tzinfo=TZ),
            status="answered",
            response_mode="no_data",
        )
        rows = await CheckinPolicyService(session).plan_for_date(
            user_id=USER_ID, usage_date=DAY
        )
        repeated = await CheckinPolicyService(session).plan_for_date(
            user_id=USER_ID, usage_date=DAY
        )
        covered = (
            (datetime(2026, 6, 21, 8, tzinfo=TZ), datetime(2026, 6, 21, 10, tzinfo=TZ)),
            (datetime(2026, 6, 21, 12, tzinfo=TZ), datetime(2026, 6, 21, 14, tzinfo=TZ)),
            (datetime(2026, 6, 21, 16, tzinfo=TZ), datetime(2026, 6, 21, 18, tzinfo=TZ)),
        )
        assert rows
        assert [row.id for row in repeated] == [row.id for row in rows]
        assert all(
            not _overlaps(row, start, end)
            for row in rows
            for start, end in covered
        )


async def test_new_coverage_expires_stale_pending_without_small_gap_noise() -> None:
    async with _session_ctx() as session:
        await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=DAY, status="confirmed"
        )
        service = CheckinPolicyService(session)
        initial = await service.plan_for_date(user_id=USER_ID, usage_date=DAY)
        await ActivityEntryService(session).create(
            user_id=USER_ID,
            start_at=datetime(2026, 6, 21, 0, tzinfo=TZ),
            end_at=datetime(2026, 6, 21, 23, 45, tzinfo=TZ),
            title="Confirmed day",
            category="work",
            source="test",
            owner_confirmed=True,
        )
        assert await service.plan_for_date(user_id=USER_ID, usage_date=DAY) == []
        rows = list((await session.execute(select(Checkin))).scalars().all())
        assert len(rows) == len(initial)
        assert all(row.status == "expired" for row in rows)


async def main_async() -> None:
    await test_no_confirmed_schedule_means_no_checkins()
    await test_policy_is_idempotent_and_suppresses_protected_windows()
    await test_120_minute_interval()
    await test_confirmed_activity_and_unknown_are_not_prompted_again()
    await test_new_coverage_expires_stale_pending_without_small_gap_noise()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: check-in policy is durable, idempotent, and protected-slot aware")


if __name__ == "__main__":
    main()
