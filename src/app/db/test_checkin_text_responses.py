"""Stage 20.5-C text routing to active check-ins."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import Base
from app.handlers.checkins import try_handle_checkin_text
from app.services.daily_control_service import CheckinService

USER_ID = 123456789
TZ = timezone(timedelta(hours=5))


class _Message:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=USER_ID)
        self.chat = SimpleNamespace(id=555)
        self.answers = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_checkin_text_") as tmp:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(Path(tmp) / 'text.db').as_posix()}")
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def _active(session, hour_offset: int = -1):
    start = now_tz() + timedelta(hours=hour_offset)
    return await CheckinService(session).create(
        user_id=USER_ID, window_start=start, window_end=start + timedelta(hours=1),
        prompted_at=now_tz() - timedelta(minutes=5), status="sent",
    )


async def test_high_confidence_text_answers_active_checkins() -> None:
    for text, mode in (("всё по плану", "aligned"), ("начал", "started"),
                       ("позже", "deferred"), ("не помню", "unknown")):
        async with _session_ctx() as session:
            row = await _active(session)
            message = _Message(text)
            handled = await try_handle_checkin_text(
                message, session,
                settings=SimpleNamespace(allowed_telegram_id=USER_ID),
            )
            assert handled is True
            assert row.response_mode == mode


async def test_no_context_or_ambiguous_text_continues_capture() -> None:
    async with _session_ctx() as session:
        assert await try_handle_checkin_text(
            _Message("всё по плану"), session,
            settings=SimpleNamespace(allowed_telegram_id=USER_ID),
        ) is False
        await _active(session)
        message = _Message("добавь задачу купить молоко")
        assert await try_handle_checkin_text(
            message, session,
            settings=SimpleNamespace(allowed_telegram_id=USER_ID),
        ) is False


async def main_async() -> None:
    await test_high_confidence_text_answers_active_checkins()
    await test_no_context_or_ambiguous_text_continues_capture()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: text replies route only to active check-ins")


if __name__ == "__main__":
    main()
