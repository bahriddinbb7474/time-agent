from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.capture_confirmation_service import (
    CAPTURE_ACTION_BOSS,
    CAPTURE_ACTION_CANCEL,
    CAPTURE_ACTION_LATER,
    CAPTURE_ACTION_TASK,
    CAPTURE_CALLBACK_PREFIX,
    build_capture_button_specs,
    build_capture_confirmation_text,
)
from app.services.capture_action_service import CaptureActionService
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


@router.callback_query(F.data.startswith(f"{CAPTURE_CALLBACK_PREFIX}:"))
async def capture_confirmation_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    action = (callback.data or "").removeprefix(f"{CAPTURE_CALLBACK_PREFIX}:")
    key = build_capture_key(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    draft = PENDING_CAPTURE_DRAFTS.pop(key, None)

    if action == CAPTURE_ACTION_CANCEL:
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    if draft is None:
        await _finalize_capture_ui(callback)
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    service = CaptureActionService(
        session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    if action == CAPTURE_ACTION_LATER:
        task = await service.create_later_from_text(draft.text)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"На потом: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_BOSS:
        task = await service.create_boss_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"Boss задача: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_TASK:
        result = await service.create_task_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await _finalize_capture_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
        return

    await _finalize_capture_ui(callback)
    await callback.answer("Неизвестное действие.", show_alert=True)


async def _finalize_capture_ui(callback: CallbackQuery) -> None:
    if callback.message is None:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        return
