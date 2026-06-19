from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import DailySchedule


CALLBACK_PREFIX = "schedule_review"


def schedule_review_callback(action: str, schedule: DailySchedule) -> str:
    usage_date = schedule.usage_date.strftime("%Y%m%d")
    return f"{CALLBACK_PREFIX}:{action}:{schedule.id}:{schedule.version}:{usage_date}"


def build_schedule_review_keyboard(schedule: DailySchedule) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm schedule",
                    callback_data=schedule_review_callback("confirm", schedule),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Edit",
                    callback_data=schedule_review_callback("edit", schedule),
                ),
                InlineKeyboardButton(
                    text="❌ Decline",
                    callback_data=schedule_review_callback("decline", schedule),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Rebuild",
                    callback_data=schedule_review_callback("rebuild", schedule),
                )
            ],
        ]
    )


def build_schedule_edit_keyboard(schedule: DailySchedule) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Rebuild current inputs",
                    callback_data=schedule_review_callback("rebuild", schedule),
                )
            ]
        ]
    )


def build_confirmed_schedule_keyboard(schedule: DailySchedule) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Edit",
                    callback_data=schedule_review_callback("edit", schedule),
                ),
                InlineKeyboardButton(
                    text="🔄 Rebuild draft",
                    callback_data=schedule_review_callback("rebuild", schedule),
                ),
            ]
        ]
    )
