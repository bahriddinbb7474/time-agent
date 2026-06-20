"""Stage 20.5-D safe owner-provided other response flow."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import ActivityEntry, Base
from app.handlers.checkins import checkin_callback, try_handle_checkin_text
from app.services.daily_control_service import CheckinService

USER_ID = 123456789


class _Event:
    def __init__(self, text=None, data=None):
        self.text = text
        self.data = data
        self.from_user = SimpleNamespace(id=USER_ID)
        self.answers = []

    async def answer(self, text, show_alert=False, reply_markup=None):
        self.answers.append(text)


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_other_response_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'other.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_other_button_then_text_creates_owner_fact_once() -> None:
    async with _session_ctx() as session:
        row = await CheckinService(session).create(
            user_id=USER_ID,
            window_start=now_tz() - timedelta(hours=1),
            window_end=now_tz(), prompted_at=now_tz() - timedelta(minutes=5),
            status="sent",
        )
        settings = SimpleNamespace(allowed_telegram_id=USER_ID)
        await checkin_callback(_Event(data=f"checkin:{row.id}:other"), session, settings)
        assert row.status == "open" and row.response_mode == "other"
        message = _Event(text="Гулял с детьми")
        assert await try_handle_checkin_text(message, session, settings) is True
        assert await try_handle_checkin_text(message, session, settings) is False
        entries = list((await session.execute(select(ActivityEntry))).scalars())
        assert len(entries) == 1
        assert entries[0].title == "Гулял с детьми"
        assert entries[0].owner_confirmed is True
        assert entries[0].waste_marked_by_owner is False


async def test_too_long_other_text_is_rejected() -> None:
    async with _session_ctx() as session:
        row = await CheckinService(session).create(
            user_id=USER_ID,
            window_start=now_tz() - timedelta(hours=1),
            window_end=now_tz(), prompted_at=now_tz() - timedelta(minutes=5),
            status="open", response_mode="other",
        )
        message = _Event(text="x" * 257)
        assert await try_handle_checkin_text(
            message, session, SimpleNamespace(allowed_telegram_id=USER_ID)
        ) is True
        assert row.status == "open"
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0


async def main_async() -> None:
    await test_other_button_then_text_creates_owner_fact_once()
    await test_too_long_other_text_is_rejected()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: other check-in text is stored only as an owner-provided fact")


if __name__ == "__main__":
    main()
