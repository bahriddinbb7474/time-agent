from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.services.daily_context_service import DailyContextService
from app.services.rules_service import RulesService
from app.services.task_service import TaskService
from app.services.google_calendar_service import GoogleCalendarService
from app.services.family_contact_service import FamilyContactService
from app.services.prayer_times_service import PrayerTimesService

router = Router()


@router.message(Command("siyam_on"))
async def siyam_on_today_cmd(message: Message, session: AsyncSession):
    policy = await DailyContextService(session).set_explicit_siyam_for_today(
        is_siyam_day=True,
    )
    source = policy.siyam_state_source
    await message.answer(f"Siyam на сегодня: ON ({source}).")


@router.message(Command("siyam_off"))
async def siyam_off_today_cmd(message: Message, session: AsyncSession):
    policy = await DailyContextService(session).set_explicit_siyam_for_today(
        is_siyam_day=False,
    )
    source = policy.siyam_state_source
    await message.answer(f"Siyam на сегодня: OFF ({source}).")


@router.message(Command("today"))
async def today_cmd(message: Message, session: AsyncSession):
    now = now_tz()
    today = now.date()
    daily_policy = await DailyContextService(session).get_policy_for_date(today)

    rules = await RulesService(session).list_rules()
    timed, floating = await TaskService(session).list_today()

    existing_today_titles = [t.title for t in (timed + floating)]

    try:
        family_candidates = await FamilyContactService(session).build_today_reminder_candidates(
            existing_task_titles=existing_today_titles,
        )
    except Exception:
        family_candidates = []

    # ---- Google Calendar service ----
    # простой режим: только чтение событий
    gcal_service = GoogleCalendarService(
        session_factory=lambda: session,
        bot_notify_fn=lambda *_: None,
    )

    try:
        gcal_events = await gcal_service.get_today_events()
    except Exception:
        gcal_events = []
    # ---------------------------------

    lines = ["План на сегодня\n"]

    siyam_status = "ON" if daily_policy and daily_policy.is_siyam_day else "OFF"
    siyam_source = (
        daily_policy.siyam_state_source
        if daily_policy is not None
        else DailyContextService.SIYAM_SOURCE_HEURISTIC
    )
    lines.append(f"Siyam today: {siyam_status} ({siyam_source})")

    prayer_times = await PrayerTimesService(session).get_prayer_times(today)
    maghrib_at = datetime.combine(today, prayer_times.maghrib, tzinfo=now.tzinfo)
    hydration_status = (
        "OFF (Siyam active)"
        if daily_policy and daily_policy.is_siyam_day and now < maghrib_at
        else "ON (Drink water)"
    )
    lines.append(f"Hydration: {hydration_status}")

    # Protected slots
    lines.append("Защищённые слоты:")
    for r in rules:
        lines.append(f"• {r.name}: {r.start_time}-{r.end_time}")

    # Google Calendar
    lines.append("\nGoogle Calendar:")
    if gcal_events:
        for e in gcal_events:
            lines.append(f"• {e['start']} — {e['summary']}")
    else:
        lines.append("• (нет событий)")

    # Timed tasks
    lines.append("\nЗадачи по времени:")
    if timed:
        for t in timed:
            lines.append(f"• {t.planned_at} — {t.title} ({t.duration_min} мин)")
    else:
        lines.append("• (пока нет)")

    # Family reminder candidates (controlled, no auto-creation)
    lines.append("\nFamily reminder candidates:")
    if family_candidates:
        for c in family_candidates:
            lines.append(f"- {c.title}")
    else:
        lines.append("- (none)")

    # Floating tasks
    lines.append("\nЗадачи без времени:")
    if floating:
        for t in floating:
            lines.append(f"• #{t.id} — {t.title}")
    else:
        lines.append("• (пока нет)")

    await message.answer("\n".join(lines))


