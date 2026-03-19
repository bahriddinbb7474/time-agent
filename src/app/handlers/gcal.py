from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.google_calendar_service import GoogleCalendarService
from app.services.google_reconciliation_service import GoogleReconciliationService


def _build_google_conflict_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Оставить как есть",
                    callback_data=f"gcal_conflict:keep:{task_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🟢 Показать безопасный слот",
                    callback_data=f"gcal_conflict:safe:{task_id}",
                )
            ],
        ]
    )


def build_gcal_router(gcal_service: GoogleCalendarService) -> Router:
    router = Router()

    @router.message(Command("gcal_test"))
    async def gcal_test(message: Message):
        ok = await gcal_service.is_connected()

        if ok:
            await message.answer("Google Calendar подключен ✅")
        else:
            await message.answer(
                "Google Calendar не подключен 🔐\nИспользуй /gcal_connect"
            )

    @router.message(Command("gcal_connect"))
    async def gcal_connect(message: Message):
        user_id = message.from_user.id

        status = await gcal_service.get_auth_url_and_start_server(user_id)

        if status.connected:
            await message.answer("Уже подключено ✅")
            return

        await message.answer(
            "Требуется авторизация Google Calendar 🔐\n\n"
            "1) Откройте ссылку ниже в браузере\n"
            "2) Разрешите доступ\n"
            "3) После редиректа увидите страницу Authorized ✅\n\n"
            f"{status.auth_url}"
        )

    @router.message(Command("gcal_today"))
    async def gcal_today(message: Message):
        try:
            events = await gcal_service.get_today_events()
        except Exception as e:
            await message.answer(f"Ошибка чтения Google Calendar ❌\n{e}")
            return

        if not events:
            await message.answer("Сегодня в Google Calendar событий нет.")
            return

        lines = ["📅 События Google Calendar на сегодня:\n"]

        for idx, event in enumerate(events, start=1):
            summary = event.get("summary", "(no title)")
            start_value = event.get("start", "-")
            end_value = event.get("end", "-")
            status = event.get("status", "-")

            lines.append(
                f"{idx}. {summary}\n"
                f"   start: {start_value}\n"
                f"   end:   {end_value}\n"
                f"   status:{status}"
            )

        await message.answer("\n\n".join(lines))

    @router.message(Command("gcal_debug"))
    async def gcal_debug(message: Message):
        try:
            info = await gcal_service.get_debug_info()
        except Exception as e:
            await message.answer(f"Ошибка диагностики Google Calendar ❌\n{e}")
            return

        text = (
            "🛠 Google Calendar debug\n\n"
            f"app_tz: {info.get('app_tz')}\n"
            f"day_start: {info.get('day_start')}\n"
            f"day_end: {info.get('day_end')}\n\n"
            f"calendar_id: {info.get('calendar_id')}\n"
            f"calendar_summary: {info.get('calendar_summary')}\n"
            f"calendar_time_zone: {info.get('calendar_time_zone')}\n"
            f"events_count: {info.get('events_count')}"
        )

        await message.answer(text)

    @router.message(Command("gcal_pull"))
    async def gcal_pull(message: Message, session: AsyncSession):
        service = GoogleReconciliationService(
            session=session,
            gcal_service=gcal_service,
        )

        try:
            summary = await service.pull_and_reconcile()
        except Exception as e:
            await message.answer(f"Ошибка Google pull ❌\n{e}")
            return

        await message.answer(summary.to_user_text())

        for item in summary.conflict_items:
            text = (
                f"⚠️ Событие из Google Calendar конфликтует с {item.conflict_label}.\n\n"
                f"Событие: {item.summary}\n"
                f"Время: {item.start_at_text}\n"
                f"Конфликт: {item.conflict_message}\n\n"
                "Что делаем?"
            )

            await message.answer(
                text,
                reply_markup=_build_google_conflict_keyboard(item.task_id),
            )

    @router.callback_query(F.data.startswith("gcal_conflict:keep:"))
    async def gcal_conflict_keep(
        callback: CallbackQuery,
        session: AsyncSession,
    ):
        if callback.message is None:
            await callback.answer("Сообщение не найдено.", show_alert=True)
            return

        task_id_raw = callback.data.removeprefix("gcal_conflict:keep:")
        if not task_id_raw.isdigit():
            await callback.answer("Некорректный task_id.", show_alert=True)
            return

        service = GoogleReconciliationService(
            session=session,
            gcal_service=gcal_service,
        )
        text = await service.build_conflict_action_text(task_id=int(task_id_raw))

        await callback.answer("Оставлено как есть.")
        if text is None:
            await callback.message.edit_text(
                "✅ Конфликт уже не актуален. Событие оставлено как есть."
            )
            return

        await callback.message.edit_text(f"{text}\n\n✅ Оставлено как есть.")

    @router.callback_query(F.data.startswith("gcal_conflict:safe:"))
    async def gcal_conflict_safe(
        callback: CallbackQuery,
        session: AsyncSession,
    ):
        if callback.message is None:
            await callback.answer("Сообщение не найдено.", show_alert=True)
            return

        task_id_raw = callback.data.removeprefix("gcal_conflict:safe:")
        if not task_id_raw.isdigit():
            await callback.answer("Некорректный task_id.", show_alert=True)
            return

        service = GoogleReconciliationService(
            session=session,
            gcal_service=gcal_service,
        )
        safe_text = await service.build_safe_slot_message(task_id=int(task_id_raw))

        await callback.answer("Проверяю безопасный слот.")
        await callback.message.edit_text(safe_text)

    return router
