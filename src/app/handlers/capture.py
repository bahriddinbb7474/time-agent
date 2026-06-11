from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.capture_confirmation_service import (
    CAPTURE_ACTION_BOSS,
    CAPTURE_ACTION_CANCEL,
    CAPTURE_ACTION_EXPIRED_CANCEL,
    CAPTURE_ACTION_EXPIRED_LATER,
    CAPTURE_ACTION_LATER,
    CAPTURE_ACTION_TASK,
    CAPTURE_CALLBACK_PREFIX,
    build_capture_button_specs,
    build_capture_confirmation_text,
    build_expired_capture_button_specs,
    build_expired_capture_text,
)
from app.services.capture_action_service import CaptureActionService
from app.services.capture_draft_service import CaptureDraftService
from app.services.capture_router_service import (
    CAPTURE_KIND_IGNORE,
    CaptureRouterService,
)
from app.services.stt_provider import DisabledSTTProvider


router = Router()


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


def build_expired_capture_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button.text,
                    callback_data=button.callback_data,
                )
            ]
            for button in build_expired_capture_button_specs()
        ]
    )


@router.message(F.voice)
async def capture_voice_message(message: Message):
    result = await DisabledSTTProvider().transcribe_voice(
        message.voice.file_id if message.voice else ""
    )
    await message.answer(result.user_message)


@router.message(F.text)
async def capture_text_message(message: Message, session: AsyncSession):
    if message.text is None or message.chat is None or message.from_user is None:
        return

    draft = CaptureRouterService().classify_text(message.text)
    if draft.kind == CAPTURE_KIND_IGNORE:
        return

    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )

    expired_record = await draft_service.get_latest_expired_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if expired_record is not None:
        await message.answer(
            build_expired_capture_text(draft_service.to_capture_draft(expired_record)),
            reply_markup=build_expired_capture_keyboard(),
        )
        return

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if pending_record is not None:
        await message.answer(
            build_capture_confirmation_text(
                draft_service.to_capture_draft(pending_record)
            ),
            reply_markup=build_capture_confirmation_keyboard(),
        )
        return

    await draft_service.create_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        draft=draft,
    )

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
    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    service = CaptureActionService(
        session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    if action in {CAPTURE_ACTION_EXPIRED_LATER, CAPTURE_ACTION_EXPIRED_CANCEL}:
        expired_record = await draft_service.get_latest_expired_draft(
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
        )
        if expired_record is None:
            await _finalize_capture_ui(callback)
            await callback.answer("Черновик не найден.", show_alert=True)
            return

        if action == CAPTURE_ACTION_EXPIRED_LATER:
            task = await service.create_later_from_text(expired_record.raw_text)
            await draft_service.mark_confirmed(expired_record)
            await _finalize_capture_ui(callback)
            await callback.message.answer(f"На потом: #{task.id}")
            await callback.answer()
            return

        await draft_service.mark_cancelled(expired_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    if action == CAPTURE_ACTION_CANCEL:
        if pending_record is not None:
            await draft_service.mark_cancelled(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    if action not in {CAPTURE_ACTION_LATER, CAPTURE_ACTION_BOSS, CAPTURE_ACTION_TASK}:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    if pending_record is None:
        await _finalize_capture_ui(callback)
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    draft = draft_service.to_capture_draft(pending_record)

    if action == CAPTURE_ACTION_LATER:
        task = await service.create_later_from_text(draft.text)
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"На потом: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_BOSS:
        task = await service.create_boss_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"Boss задача: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_TASK:
        result = await service.create_task_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
        return


async def _finalize_capture_ui(callback: CallbackQuery) -> None:
    if callback.message is None:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        return
