from __future__ import annotations

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.services.capture_confirmation_service import (
    build_capture_button_specs,
    build_capture_confirmation_text,
)
from app.services.capture_router_service import (
    CAPTURE_KIND_IGNORE,
    CaptureDraft,
    CaptureRouterService,
)


router = Router()

PENDING_CAPTURE_DRAFTS: dict[tuple[int, int], CaptureDraft] = {}


def build_capture_key(*, chat_id: int, user_id: int) -> tuple[int, int]:
    return chat_id, user_id


def build_capture_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button.text,
                    callback_data=button.callback_data,
                )
            ]
            for button in build_capture_button_specs()
        ]
    )


@router.message(F.text)
async def capture_text_message(message: Message):
    if message.text is None or message.chat is None or message.from_user is None:
        return

    draft = CaptureRouterService().classify_text(message.text)
    if draft.kind == CAPTURE_KIND_IGNORE:
        return

    key = build_capture_key(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    PENDING_CAPTURE_DRAFTS[key] = draft

    await message.answer(
        build_capture_confirmation_text(draft),
        reply_markup=build_capture_confirmation_keyboard(),
    )
