from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.services.checkin_response_service import CheckinResponseService
from app.services.daily_control_service import DailyControlNotFoundError


router = Router()


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
        row = await CheckinResponseService(session).respond(
            checkin_id=checkin_id, user_id=user_id, action=action
        )
    except (ValueError, DailyControlNotFoundError):
        await callback.answer("Check-in не найден или кнопка устарела.", show_alert=True)
        return
    labels = {
        "aligned": "Отмечено: всё по плану.",
        "started": "Отмечено: начал.",
        "deferred": "Check-in отложен.",
        "unknown": "Записано: нет данных.",
        "other": "Свободный ответ будет подключён следующим шагом.",
    }
    await callback.answer(labels.get(row.response_mode, "Ответ уже учтён."))

