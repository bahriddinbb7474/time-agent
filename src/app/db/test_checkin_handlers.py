"""Stage 20.4-C owner-only check-in callback tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ActivityEntry, Base
from app.handlers.checkins import checkin_callback, checkin_test_cmd
from app.keyboards.checkins import build_checkin_keyboard
from app.services.daily_control_service import CheckinService

USER_ID = 123456789
TZ = timezone(timedelta(hours=5))


class _Callback:
    def __init__(self, data: str, user_id: int = USER_ID) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, show_alert=False):
        self.answers.append((text, show_alert))


class _Bot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, user_id, text, reply_markup=None):
        self.sent.append((user_id, text, reply_markup))


class _Message:
    def __init__(self, user_id: int = USER_ID) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.bot = _Bot()
        self.answers = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_checkin_handlers_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'handlers.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_actions_are_owner_only_and_idempotent() -> None:
    async with _session_ctx() as session:
        row = await CheckinService(session).create(
            user_id=USER_ID,
            window_start=datetime(2026, 6, 21, 9, tzinfo=TZ),
            window_end=datetime(2026, 6, 21, 10, tzinfo=TZ),
            prompted_at=datetime(2026, 6, 21, 10, tzinfo=TZ),
            status="sent", usage_date=date(2026, 6, 21),
        )
        settings = SimpleNamespace(allowed_telegram_id=USER_ID)
        callback = _Callback(f"checkin:{row.id}:aligned")
        await checkin_callback(callback, session, settings=settings)
        await checkin_callback(callback, session, settings=settings)
        assert row.status == "answered"
        assert row.response_mode == "aligned"
        denied = _Callback(f"checkin:{row.id}:defer", USER_ID + 1)
        await checkin_callback(denied, session, settings=settings)
        assert denied.answers == []


async def test_missing_is_safe_and_keyboard_complete() -> None:
    async with _session_ctx() as session:
        callback = _Callback("checkin:999:unknown")
        await checkin_callback(
            callback, session, settings=SimpleNamespace(allowed_telegram_id=USER_ID)
        )
        assert callback.answers[-1][1] is True
    buttons = [b for row in build_checkin_keyboard(1).inline_keyboard for b in row]
    assert len(buttons) == 5


async def test_checkin_test_sends_nearest_pending_and_creates_fallback_window() -> None:
    async with _session_ctx() as session:
        service = CheckinService(session)
        deferred = await service.create(
            user_id=USER_ID,
            window_start=datetime(2026, 6, 21, 8, tzinfo=TZ),
            window_end=datetime(2026, 6, 21, 9, tzinfo=TZ),
            prompted_at=datetime(2026, 6, 21, 9, tzinfo=TZ),
            status="deferred", response_mode="protected_slot",
        )
        pending = await service.create(
            user_id=USER_ID,
            window_start=datetime(2026, 6, 21, 9, tzinfo=TZ),
            window_end=datetime(2026, 6, 21, 10, tzinfo=TZ),
            prompted_at=datetime(2026, 6, 21, 10, tzinfo=TZ),
        )
        message = _Message()
        settings = SimpleNamespace(allowed_telegram_id=USER_ID)
        await checkin_test_cmd(message, session, settings=settings)
        assert len(message.bot.sent) == 1
        assert "Сейчас по плану:" in message.bot.sent[0][1]
        assert pending.status == "sent"
        assert deferred.status == "deferred"
        assert "Тестовый check-in создан" in message.answers[-1][0]
        await checkin_callback(_Callback(f"checkin:{pending.id}:unknown"), session, settings=settings)
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0

        second = _Message()
        await checkin_test_cmd(second, session, settings=settings)
        assert len(second.bot.sent) == 1
        assert "Сейчас по плану:" in second.bot.sent[0][1]
        assert "Тестовый check-in создан" in second.answers[-1][0]
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0


async def test_unknown_and_defer_create_no_activity_or_waste() -> None:
    async with _session_ctx() as session:
        service = CheckinService(session)
        settings = SimpleNamespace(allowed_telegram_id=USER_ID)
        for hour, action, expected in ((10, "unknown", "unknown"), (11, "defer", "deferred")):
            row = await service.create(
                user_id=USER_ID,
                window_start=datetime(2026, 6, 21, hour, tzinfo=TZ),
                window_end=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                prompted_at=datetime(2026, 6, 21, hour + 1, tzinfo=TZ),
                status="sent",
            )
            await checkin_callback(
                _Callback(f"checkin:{row.id}:{action}"), session, settings=settings
            )
            assert row.response_mode == expected
        assert await session.scalar(select(func.count()).select_from(ActivityEntry)) == 0


async def main_async() -> None:
    await test_actions_are_owner_only_and_idempotent()
    await test_missing_is_safe_and_keyboard_complete()
    await test_checkin_test_sends_nearest_pending_and_creates_fallback_window()
    await test_unknown_and_defer_create_no_activity_or_waste()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: check-in callbacks are owner-only and idempotent")


if __name__ == "__main__":
    main()
