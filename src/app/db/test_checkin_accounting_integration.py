"""Stage 20.4-D check-in/accounting integration tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ActivityEntry, Base
from app.services.checkin_response_service import CheckinResponseService
from app.services.daily_control_accounting_service import DailyControlAccountingService
from app.services.daily_control_service import CheckinService

USER_ID = 123456789
DAY = date(2026, 6, 21)
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_checkin_accounting_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'accounting.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_answers_are_readable_without_fake_activity() -> None:
    async with _session_ctx() as session:
        rows = []
        for hour in (9, 10, 11):
            rows.append(await CheckinService(session).create(
                user_id=USER_ID, usage_date=DAY,
                window_start=datetime(2026, 6, 21, hour, tzinfo=TZ),
                window_end=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                prompted_at=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                status="sent",
            ))
        responses = CheckinResponseService(session)
        await responses.respond(checkin_id=rows[0].id, user_id=USER_ID, action="aligned")
        await responses.respond(checkin_id=rows[1].id, user_id=USER_ID, action="unknown")
        await responses.respond(checkin_id=rows[2].id, user_id=USER_ID, action="defer")
        summary = await DailyControlAccountingService(session).summarize(
            user_id=USER_ID, usage_date=DAY
        )
        assert summary.aligned_checkins == 1
        assert summary.unknown_checkins == 1
        assert summary.unknown_minutes == 60.0
        assert summary.no_data_minutes == 1380.0
        assert summary.deferred_checkins == 1
        assert summary.owner_marked_waste_minutes == 0
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0


def main() -> None:
    asyncio.run(test_answers_are_readable_without_fake_activity())
    print("PASS: check-in answers integrate with accounting without fake activity")


if __name__ == "__main__":
    main()
