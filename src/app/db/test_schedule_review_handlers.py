"""Stage 20.3-B manual schedule review command tests."""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.schedule_review import schedule_tomorrow_cmd
from app.keyboards.schedule_review import CALLBACK_PREFIX, build_schedule_review_keyboard
from app.services.daily_control_service import DailyControlValidationError


OWNER_ID = 123456789


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
    with (
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
    with patch(
        "app.handlers.schedule_review.ScheduleProposalBuilder",
        return_value=builder,
    ):
        await schedule_tomorrow_cmd(message, MagicMock(), settings=_settings())

    assert len(message.answers) == 1
    text, reply_markup = message.answers[0]
    assert "конфликта защищённых интервалов" in text
    assert "Расписание не подтверждено" in text
    assert "protected overlap details" not in text
    assert reply_markup is None


async def main_async() -> None:
    await test_owner_command_builds_tomorrow_draft_and_formats_it()
    await test_non_owner_command_is_ignored()
    await test_builder_validation_error_replies_fail_closed()


def main() -> None:
    test_keyboard_has_safe_review_actions()
    asyncio.run(main_async())
    print("PASS: /schedule_tomorrow shows an owner-only proposal review")


if __name__ == "__main__":
    main()
