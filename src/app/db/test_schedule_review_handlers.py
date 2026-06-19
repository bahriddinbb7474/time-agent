"""Stage 20.3-B manual schedule review command tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, TimeBlock
from app.handlers.schedule_review import schedule_tomorrow_cmd
from app.keyboards.schedule_review import CALLBACK_PREFIX, build_schedule_review_keyboard
from app.services.daily_control_service import (
    DailyControlValidationError,
    DailyScheduleService,
    TimeBlockService,
)


OWNER_ID = 123456789
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_review_handler_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'handler.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


class _Message:
    def __init__(self, user_id: int = OWNER_ID) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


def _settings():
    return SimpleNamespace(
        allowed_telegram_id=OWNER_ID,
        tz="Asia/Tashkent",
    )


def _schedule():
    return SimpleNamespace(
        id=7,
        version=1,
        usage_date=date(2026, 6, 21),
    )


def test_keyboard_has_safe_review_actions() -> None:
    keyboard = build_schedule_review_keyboard(_schedule())
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "✅ Confirm schedule",
        "✏️ Edit",
        "❌ Decline",
        "🔄 Rebuild",
    ]
    assert all(button.callback_data.startswith(CALLBACK_PREFIX + ":") for button in buttons)
    assert all(len(button.callback_data.encode()) <= 64 for button in buttons)


async def test_owner_command_builds_tomorrow_draft_and_formats_it() -> None:
    message = _Message()
    proposal = SimpleNamespace(schedule=_schedule())
    builder = MagicMock()
    builder.build = AsyncMock(return_value=proposal)
    fixed_now = SimpleNamespace(date=lambda: date(2026, 6, 20))
    confirmation = MagicMock()
    confirmation.get_confirmed_for_date = AsyncMock(return_value=None)
    with (
        patch(
            "app.handlers.schedule_review.ScheduleConfirmationService",
            return_value=confirmation,
        ),
        patch("app.handlers.schedule_review.ScheduleProposalBuilder", return_value=builder),
        patch("app.handlers.schedule_review.format_schedule_proposal", return_value="summary"),
        patch("app.handlers.schedule_review.now_tz", return_value=fixed_now),
    ):
        await schedule_tomorrow_cmd(message, MagicMock(), settings=_settings())

    builder.build.assert_awaited_once_with(
        usage_date=date(2026, 6, 21),
        user_id=OWNER_ID,
        timezone="Asia/Tashkent",
    )
    assert message.answers[0][0] == "summary"
    assert message.answers[0][1] is not None


async def test_non_owner_command_is_ignored() -> None:
    message = _Message(OWNER_ID + 1)
    with patch("app.handlers.schedule_review.ScheduleProposalBuilder") as builder:
        await schedule_tomorrow_cmd(message, MagicMock(), settings=_settings())
    builder.assert_not_called()
    assert message.answers == []


async def test_builder_validation_error_replies_fail_closed() -> None:
    message = _Message()
    builder = MagicMock()
    builder.build = AsyncMock(
        side_effect=DailyControlValidationError("protected overlap details")
    )
    confirmation = MagicMock()
    confirmation.get_confirmed_for_date = AsyncMock(return_value=None)
    with (
        patch(
            "app.handlers.schedule_review.ScheduleConfirmationService",
            return_value=confirmation,
        ),
        patch(
            "app.handlers.schedule_review.ScheduleProposalBuilder",
            return_value=builder,
        ),
    ):
        await schedule_tomorrow_cmd(message, MagicMock(), settings=_settings())

    assert len(message.answers) == 1
    text, reply_markup = message.answers[0]
    assert "конфликта защищённых интервалов" in text
    assert "Расписание не подтверждено" in text
    assert "protected overlap details" not in text
    assert reply_markup is None


async def test_confirmed_schedule_is_shown_without_calling_builder() -> None:
    message = _Message()
    confirmed = SimpleNamespace(
        id=7,
        version=1,
        usage_date=date(2026, 6, 21),
        status="confirmed",
    )
    proposal = SimpleNamespace(schedule=confirmed)
    confirmation = MagicMock()
    confirmation.get_confirmed_for_date = AsyncMock(return_value=confirmed)
    builder = MagicMock()
    builder.build = AsyncMock(
        side_effect=DailyControlValidationError("builder must not run")
    )
    fixed_now = SimpleNamespace(date=lambda: date(2026, 6, 20))
    with (
        patch(
            "app.handlers.schedule_review.ScheduleConfirmationService",
            return_value=confirmation,
        ),
        patch("app.handlers.schedule_review.ScheduleProposalBuilder", return_value=builder),
        patch("app.handlers.schedule_review._proposal_from_schedule", AsyncMock(return_value=proposal)),
        patch("app.handlers.schedule_review.format_schedule_proposal", return_value="confirmed summary"),
        patch("app.handlers.schedule_review.now_tz", return_value=fixed_now),
    ):
        await schedule_tomorrow_cmd(message, MagicMock(), settings=_settings())

    builder.build.assert_not_awaited()
    assert message.answers[0][0] == "confirmed summary"
    buttons = [
        button
        for row in message.answers[0][1].inline_keyboard
        for button in row
    ]
    assert [button.text for button in buttons] == ["✏️ Edit", "🔄 Rebuild draft"]


async def test_repeated_confirmed_command_does_not_duplicate_blocks() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=OWNER_ID,
            usage_date=date(2026, 6, 21),
            status="confirmed",
        )
        await TimeBlockService(session).create(
            schedule_id=schedule.id,
            user_id=OWNER_ID,
            start_at=datetime(2026, 6, 21, 9, tzinfo=TZ),
            end_at=datetime(2026, 6, 21, 10, tzinfo=TZ),
            title="Existing task",
            category="work",
            block_type="task",
            flexibility="fixed",
            source_type="test",
        )
        version_before = schedule.version
        fixed_now = SimpleNamespace(date=lambda: date(2026, 6, 20))
        with patch("app.handlers.schedule_review.now_tz", return_value=fixed_now):
            await schedule_tomorrow_cmd(_Message(), session, settings=_settings())
            await schedule_tomorrow_cmd(_Message(), session, settings=_settings())

        count = await session.scalar(select(func.count()).select_from(TimeBlock))
        assert count == 1
        assert schedule.status == "confirmed"
        assert schedule.version == version_before


async def main_async() -> None:
    await test_owner_command_builds_tomorrow_draft_and_formats_it()
    await test_non_owner_command_is_ignored()
    await test_builder_validation_error_replies_fail_closed()
    await test_confirmed_schedule_is_shown_without_calling_builder()
    await test_repeated_confirmed_command_does_not_duplicate_blocks()


def main() -> None:
    test_keyboard_has_safe_review_actions()
    asyncio.run(main_async())
    print("PASS: /schedule_tomorrow shows an owner-only proposal review")


if __name__ == "__main__":
    main()
