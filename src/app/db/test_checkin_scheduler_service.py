"""Stage 20.4-B restart-safe check-in scheduler tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.checkin_scheduler_service import CheckinSchedulerService
from app.services.daily_control_service import DailyScheduleService, TimeBlockService

USER_ID = 123456789
DAY = date(2026, 6, 21)
TZ = timezone(timedelta(hours=5))


class _Scheduler:
    def __init__(self) -> None:
        self.jobs = {}

    def add_job(self, func, **kwargs) -> None:
        self.jobs[kwargs["id"]] = (func, kwargs)


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_checkin_scheduler_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'scheduler.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_recovery_is_restart_safe_and_skips_protected() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=DAY, status="confirmed"
        )
        await TimeBlockService(session).create(
            schedule_id=schedule.id, user_id=USER_ID,
            start_at=datetime(2026, 6, 21, 0, tzinfo=TZ),
            end_at=datetime(2026, 6, 21, 6, tzinfo=TZ),
            title="Sleep", category="sleep", block_type="sleep",
            flexibility="protected", source_type="test",
        )
        scheduler = _Scheduler()
        service = CheckinSchedulerService(session)
        first = await service.recover(
            scheduler=scheduler, user_id=USER_ID, today=DAY,
            now=datetime(2026, 6, 21, 0, tzinfo=TZ),
        )
        second = await service.recover(
            scheduler=scheduler, user_id=USER_ID, today=DAY,
            now=datetime(2026, 6, 21, 0, tzinfo=TZ),
        )
        assert first == second
        assert len(first) == 9
        assert len(scheduler.jobs) == 9


async def test_missing_schedule_creates_no_jobs() -> None:
    async with _session_ctx() as session:
        scheduler = _Scheduler()
        ids = await CheckinSchedulerService(session).recover(
            scheduler=scheduler, user_id=USER_ID, today=DAY,
            now=datetime(2026, 6, 21, 0, tzinfo=TZ),
        )
        assert ids == []
        assert scheduler.jobs == {}


async def main_async() -> None:
    await test_recovery_is_restart_safe_and_skips_protected()
    await test_missing_schedule_creates_no_jobs()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: check-in scheduler recovery is restart-safe")


if __name__ == "__main__":
    main()
