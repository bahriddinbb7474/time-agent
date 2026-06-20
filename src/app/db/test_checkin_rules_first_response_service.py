"""Stage 20.5-B shared rules-first response application tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ActivityEntry, Base
from app.services.checkin_response_service import CheckinResponseService
from app.services.daily_control_service import CheckinService

USER_ID = 123456789
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_rules_response_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'response.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_text_and_button_values_share_state_transitions() -> None:
    async with _session_ctx() as session:
        service = CheckinService(session)
        responses = CheckinResponseService(session)
        cases = ((9, "всё по плану", "answered", "aligned"),
                 (10, "started", "answered", "started"),
                 (11, "keyin", "deferred", "deferred"),
                 (12, "не помню", "answered", "unknown"))
        for hour, value, status, mode in cases:
            row = await service.create(
                user_id=USER_ID,
                window_start=datetime(2026, 6, 21, hour, tzinfo=TZ),
                window_end=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                prompted_at=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                status="sent",
            )
            first = await responses.respond_value(
                checkin_id=row.id, user_id=USER_ID, value=value
            )
            repeated = await responses.respond_value(
                checkin_id=row.id, user_id=USER_ID, value=value
            )
            assert first.status == status and first.response_mode == mode
            assert repeated.id == first.id
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0


def main() -> None:
    asyncio.run(test_text_and_button_values_share_state_transitions())
    print("PASS: rules-first responses share one idempotent application path")


if __name__ == "__main__":
    main()
