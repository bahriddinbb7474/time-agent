from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.services.checkin_response_service import CheckinResponseService
from app.services.daily_control_service import DailyControlNotFoundError
from app.db.models import Checkin
from app.services.checkin_scheduler_service import deliver_pending_checkin
from app.services.checkin_context_service import CheckinContextService
from app.services.checkin_response_classifier import CheckinResponseClassifier


router = Router()


async def try_handle_checkin_text(message, session: AsyncSession, settings=None) -> bool:
    settings = settings or load_config()
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if settings.allowed_telegram_id is None or user_id != settings.allowed_telegram_id:
        return False
    row = await CheckinContextService(session).get_active(user_id=user_id)
    if row is None:
        return False
    text = getattr(message, "text", None)
    intent = CheckinResponseClassifier().classify(text).intent
    if intent not in {"aligned", "started", "defer", "unknown", "cancel"}:
        return False
    updated = await CheckinResponseService(session).respond_value(
        checkin_id=row.id, user_id=user_id, value=text or ""
    )
    labels = {
        "aligned": "Отмечено: всё по плану.",
        "started": "Отмечено: начал.",
        "deferred": "Check-in отложен.",
        "unknown": "Записано: нет данных.",
        "cancel": "Check-in отменён.",
    }
    await message.answer(labels.get(updated.response_mode, "Ответ учтён."))
    return True


@router.message(Command("checkin_test"))
async def checkin_test_cmd(message: Message, session: AsyncSession, settings=None) -> None:
    settings = settings or load_config()
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if settings.allowed_telegram_id is None or user_id != settings.allowed_telegram_id:
        return
    result = await session.execute(
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.status == "pending")
        .order_by(Checkin.window_start, Checkin.id)
        .limit(1)
    )
    checkin = result.scalar_one_or_none()
    if checkin is None:
        await message.answer("Нет ожидающих check-in для безопасной проверки.")
        return
    delivered = await deliver_pending_checkin(
        session,
        checkin_id=checkin.id,
        bot=message.bot,
        user_id=user_id,
    )
    if not delivered:
        await message.answer("Check-in уже обработан. Попробуй команду ещё раз позже.")


@router.callback_query(F.data.startswith("checkin:"))
async def checkin_callback(callback: CallbackQuery, session: AsyncSession, settings=None) -> None:
    settings = settings or load_config()
    user_id = getattr(getattr(callback, "from_user", None), "id", None)
    if settings.allowed_telegram_id is None or user_id != settings.allowed_telegram_id:
        return
    try:
        prefix, raw_id, action = (callback.data or "").split(":")
        if prefix != "checkin":
            raise ValueError
        checkin_id = int(raw_id)
        row = await CheckinResponseService(session).respond_value(
            checkin_id=checkin_id, user_id=user_id, value=action
        )
    except (ValueError, DailyControlNotFoundError):
        await callback.answer("Check-in не найден или кнопка устарела.", show_alert=True)
        return
    labels = {
        "aligned": "Отмечено: всё по плану.",
        "started": "Отмечено: начал.",
        "deferred": "Check-in отложен.",
        "unknown": "Записано: нет данных.",
        "other": "Напиши следующим сообщением, что происходило фактически.",
    }
    await callback.answer(labels.get(row.response_mode, "Ответ уже учтён."))
