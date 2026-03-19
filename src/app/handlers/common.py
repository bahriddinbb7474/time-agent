from datetime import date, datetime, timedelta
import logging
import json

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.time import APP_TZ
from app.db import crud
from app.db.database import get_sessionmaker
from app.db.models import AlertQueue
from app.scheduler.jobs import morning_briefing, _schedule_same_alert
from app.services.prayer_times_service import PrayerTimesService

router = Router()
logger = logging.getLogger("time-agent.handlers.common")


@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    text = (
        "👋 Приветствую. Я твой персональный ассистент по управлению временем.\n\n"
        "Я защищаю твои приоритеты:\n"
        "1) 🙏 Молитва\n"
        "2) 👨‍👩‍👧‍👦 Семья\n"
        "3) 💼 Работа\n\n"
        "Команды:\n"
        "• /rules - защищённые слоты (неприкосновенное время)\n"
        "• /prayer_today - время намазов на сегодня\n"
        "• /start - эта справка\n"
    )
    await message.answer(text)


@router.message(Command("test_brief"))
async def test_brief_cmd(message: Message) -> None:
    await message.answer("🧪 Запускаю тестовый утренний брифинг…")
    await morning_briefing(message.bot)


@router.message(Command("prayer_today"))
async def prayer_today_cmd(message: Message) -> None:
    Session = get_sessionmaker()

    async with Session() as session:
        service = PrayerTimesService(session)
        today = date.today()

        try:
            pt = await service.get_prayer_times(today)
        except Exception as e:
            await message.answer(f"Ошибка получения времени намаза ❌\n{e}")
            return

    lines = [
        "Время намазов на сегодня\n",
        f"Фаджр - {pt.fajr.strftime('%H:%M')}",
        f"Зухр - {pt.dhuhr.strftime('%H:%M')}",
        f"Аср - {pt.asr.strftime('%H:%M')}",
        f"Магриб - {pt.maghrib.strftime('%H:%M')}",
        f"Иша - {pt.isha.strftime('%H:%M')}",
    ]

    await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("prayer_done:"))
async def prayer_done_callback(
    callback: CallbackQuery,
    scheduler: AsyncIOScheduler,
) -> None:
    raw = callback.data or ""
    parts = raw.split(":", maxsplit=1)

    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Некорректный alert id", show_alert=True)
        return

    alert_id = int(parts[1])
    Session = get_sessionmaker()

    async with Session() as session:
        alert = await session.get(AlertQueue, alert_id)
        if alert is None:
            await callback.answer("Напоминание не найдено", show_alert=True)
            return

        if alert.alert_type != "prayer_reminder":
            await callback.answer("Это не prayer reminder", show_alert=True)
            return

        completed = await crud.complete_alert_if_open(session, alert_id=alert_id)

    if not completed:
        await callback.answer("Уже подтверждено")
        return

    _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert_id)

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception("Handler callback operation failed")

        try:
            await callback.message.answer("✅ Намаз отмечен как выполненный.")
        except Exception:
            logger.exception("Handler callback operation failed")

    await callback.answer("Намаз подтверждён ✅")


@router.callback_query(F.data.startswith("boss_done:"))
async def boss_done_callback(
    callback: CallbackQuery,
    scheduler: AsyncIOScheduler,
) -> None:
    raw = callback.data or ""
    parts = raw.split(":", maxsplit=1)

    if len(parts) != 2 or not parts[1].isdigit():
        await callback.answer("Некорректный alert id", show_alert=True)
        return

    alert_id = int(parts[1])
    Session = get_sessionmaker()

    async with Session() as session:
        alert = await session.get(AlertQueue, alert_id)
        if alert is None:
            await callback.answer("Напоминание не найдено", show_alert=True)
            return

        if alert.alert_type != "boss_critical":
            await callback.answer("Это не boss alert", show_alert=True)
            return

        completed = await crud.complete_alert_if_open(session, alert_id=alert_id)

    if not completed:
        await callback.answer("Уже подтверждено")
        return

    _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert_id)

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception("Failed to update callback message reply markup")

        try:
            await callback.message.answer(
                "✅ Critical задача отмечена как выполненная."
            )
        except Exception:
            logger.exception("Handler callback operation failed")

    await callback.answer("Critical задача подтверждена ✅")


@router.callback_query(F.data.startswith("quran_followup:read_now:"))
async def quran_followup_read_now_callback(
    callback: CallbackQuery,
    scheduler: AsyncIOScheduler,
) -> None:
    raw = callback.data or ""
    parts = raw.split(":")

    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer("Некорректный alert id", show_alert=True)
        return

    alert_id = int(parts[3])
    Session = get_sessionmaker()

    async with Session() as session:
        alert = await session.get(AlertQueue, alert_id)
        if alert is None:
            await callback.answer("Напоминание не найдено", show_alert=True)
            return

        completed = await crud.complete_alert_if_open(session, alert_id=alert_id)

    if not completed:
        await callback.answer("Уже подтверждено")
        return

    _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert_id)

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception("Handler callback operation failed")

        await callback.message.answer(
            "📖 Отлично. Напоминание закрыто.\n"
            "Можете дочитать сейчас и потом зафиксировать новый прогресс."
        )

    await callback.answer("Отмечено ✅")


@router.callback_query(F.data.startswith("quran_followup:move_tomorrow:"))
async def quran_followup_move_tomorrow_callback(
    callback: CallbackQuery,
    scheduler: AsyncIOScheduler,
) -> None:
    raw = callback.data or ""
    parts = raw.split(":")

    if len(parts) != 4 or not parts[3].isdigit():
        await callback.answer("Некорректный alert id", show_alert=True)
        return

    alert_id = int(parts[3])
    Session = get_sessionmaker()
    new_alert_id: int | None = None
    new_scheduled_for: datetime | None = None

    async with Session() as session:
        alert = await session.get(AlertQueue, alert_id)
        if alert is None:
            await callback.answer("Напоминание не найдено", show_alert=True)
            return

        completed = await crud.complete_alert_if_open(session, alert_id=alert_id)
        if not completed:
            await callback.answer("Уже подтверждено")
            return

        now = datetime.now(APP_TZ)
        tomorrow = (now + timedelta(days=1)).date()
        tomorrow_entity_id = tomorrow.isoformat()

        payload = {}
        if alert.payload_json:
            try:
                payload = json.loads(alert.payload_json)
            except Exception:
                payload = {}

        scheduled_for = now.replace(
            hour=8,
            minute=30,
            second=0,
            microsecond=0,
        ) + timedelta(days=1)

        reused_or_created = await crud.create_or_reuse_alert(
            session,
            alert_type="quran_followup",
            entity_type="quran_daily_goal",
            entity_id=tomorrow_entity_id,
            scheduled_for=scheduled_for,
            repeat_interval_min=None,
            priority=80,
            payload_json=json.dumps(
                {
                    "chat_id": payload.get("chat_id"),
                    "text": (
                        "📖 Напоминание по Корану перенесено на завтра.\n"
                        "Выберите действие:"
                    ),
                },
                ensure_ascii=False,
            ),
            status="pending",
        )

        new_alert_id = reused_or_created.id
        new_scheduled_for = reused_or_created.scheduled_for

    _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert_id)

    if new_alert_id is not None and new_scheduled_for is not None:
        _schedule_same_alert(
            alert_id=new_alert_id,
            scheduled_for=new_scheduled_for,
            scheduler=scheduler,
            bot=callback.bot,
        )

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.exception("Handler callback operation failed")

        await callback.message.answer("📈 Напоминание перенесено на завтра.")

    await callback.answer("Перенесено ✅")


def _remove_scheduled_alert_job(
    *,
    scheduler: AsyncIOScheduler,
    alert_id: int,
) -> None:
    if scheduler is None:
        return

    job_id = f"alert_{alert_id}"
    job = scheduler.get_job(job_id)
    if job is None:
        return

    try:
        scheduler.remove_job(job_id)
    except Exception:
        logger.exception("Failed to remove scheduled alert job")
