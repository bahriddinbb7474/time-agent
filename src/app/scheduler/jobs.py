import json
import logging
from datetime import date, datetime, time, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import load_config
from app.core.time import APP_TZ
from app.db import crud
from app.db.database import get_sessionmaker
from app.db.models import AlertQueue
from app.services.boss_priority_service import BossPriorityService
from app.services.family_contact_service import FamilyContactService
from app.services.prayer_times_service import PrayerTimesService
from app.services.quran_service import QuranService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.task_service import TaskService

log = logging.getLogger("time-agent.scheduler.jobs")

PRAYER_REMINDER_BEFORE_MIN = 10
DHUHR_REMINDER_AT = time(12, 45)
PRAYER_REPEAT_INTERVAL_MIN = 15
PRAYER_MAX_REPEATS_DEFAULT = 10
PRAYER_MAX_REPEATS_QUIET = 3
RECOVERY_RESCHEDULE_DELAY_SEC = 5


async def prayer_cache_job(bot=None, scheduler=None) -> None:
    """
    Nightly job:
    1) ensures prayer times are cached locally
    2) ensures prayer reminder alerts exist for today
    """
    Session = get_sessionmaker()
    cfg = load_config()

    async with Session() as session:
        service = PrayerTimesService(session)
        today = datetime.now(APP_TZ).date()
        await service.get_prayer_times(today)

        if cfg.allowed_telegram_id and scheduler is not None:
            await ensure_prayer_alerts_for_day(
                session=session,
                target_date=today,
                chat_id=cfg.allowed_telegram_id,
                scheduler=scheduler,
                bot=bot,
            )


async def morning_briefing(bot, scheduler=None) -> None:
    Session = get_sessionmaker()
    cfg = load_config()

    async with Session() as session:
        if cfg.allowed_telegram_id and scheduler is not None:
            await ensure_prayer_alerts_for_day(
                session=session,
                target_date=datetime.now(APP_TZ).date(),
                chat_id=cfg.allowed_telegram_id,
                scheduler=scheduler,
                bot=bot,
            )

        rules = await RulesService(session).list_rules()
        timed, floating = await TaskService(session).list_today()

    lines = ["рџ•— Р”РѕР±СЂРѕРµ СѓС‚СЂРѕ! РџР»Р°РЅ РЅР° СЃРµРіРѕРґРЅСЏ\n"]

    lines.append("рџ›Ў Р—Р°С‰РёС‰С‘РЅРЅС‹Рµ СЃР»РѕС‚С‹:")
    for r in rules:
        lines.append(f"вЂў {r.name}: {r.start_time}-{r.end_time}")

    lines.append("\nрџ“Њ Р—Р°РґР°С‡Рё РїРѕ РІСЂРµРјРµРЅРё:")
    if timed:
        for t in timed:
            lines.append(f"вЂў {t.planned_at} вЂ” {t.title} ({t.duration_min} РјРёРЅ)")
    else:
        lines.append("вЂў (РїРѕРєР° РЅРµС‚)")

    lines.append("\nрџ“ќ Р—Р°РґР°С‡Рё Р±РµР· РІСЂРµРјРµРЅРё:")
    if floating:
        for t in floating:
            lines.append(f"вЂў #{t.id} вЂ” {t.title}")
    else:
        lines.append("вЂў (РїРѕРєР° РЅРµС‚)")

    if cfg.allowed_telegram_id:
        await _send_hydration_runtime_ping(bot=bot, chat_id=cfg.allowed_telegram_id)
        await bot.send_message(cfg.allowed_telegram_id, "\n".join(lines))



async def _send_hydration_runtime_ping(*, bot, chat_id: int | None) -> None:
    """Minimal hydration runtime entry-point (send/check path)."""
    if not chat_id:
        return

    try:
        await bot.send_message(chat_id, "Hydration reminder: drink water.")
    except Exception:
        log.exception("Hydration runtime entry-point failed")

async def family_daily_check_job(bot=None) -> None:
    """
    Daily controlled family frequency check.

    Scope:
    - read due family reminder candidates
    - emit observable structured logs only
    - no task creation / no alert enqueue
    """
    Session = get_sessionmaker()

    try:
        async with Session() as session:
            timed, floating = await TaskService(session).list_today()
            existing_today_titles = [t.title for t in (timed + floating)]

            candidates = await FamilyContactService(session).build_today_reminder_candidates(
                existing_task_titles=existing_today_titles,
            )

            if not candidates:
                log.info("Family daily check: no due reminder candidates")
                return

            preview_titles = ", ".join(c.title for c in candidates[:5])
            log.info(
                "Family daily check: due_candidates=%s preview=%s",
                len(candidates),
                preview_titles,
            )
    except Exception:
        log.exception("Family daily check failed")


async def evening_summary(bot) -> None:
    Session = get_sessionmaker()
    cfg = load_config()

    async with Session() as session:
        timed, floating = await TaskService(session).list_today()
        quran_service = QuranService(session)
        quran_summary = await quran_service.get_daily_summary()
        prayer_section = await _build_prayer_status_section(session)

        critical_tasks = [
            t
            for t in (timed + floating)
            if "рџ”Ґ" in t.title or t.title.lower().startswith("С€РµС„ СЃСЂРѕС‡РЅРѕ:")
        ]

        open_tasks = [t for t in (timed + floating) if t.status != "done"]

        quran_lines = [quran_service.build_deficit_message(quran_summary)]

        followup_keyboard = None
        if not quran_summary.goal_reached and cfg.allowed_telegram_id:
            alert_id = await _ensure_quran_followup_alert(
                session=session,
                chat_id=cfg.allowed_telegram_id,
                summary_text=quran_service.build_deficit_message(quran_summary),
            )
            followup_keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="рџ“– Р”РѕС‡РёС‚Р°СЋ СЃРµР№С‡Р°СЃ",
                            callback_data=f"quran_followup:read_now:{alert_id}",
                        ),
                        InlineKeyboardButton(
                            text="рџ“€ РџРµСЂРµРЅРµСЃС‚Рё РЅР° Р·Р°РІС‚СЂР°",
                            callback_data=f"quran_followup:move_tomorrow:{alert_id}",
                        ),
                    ]
                ]
            )

    lines = ["рџ• Р’РµС‡РµСЂРЅРёР№ spiritual report\n"]

    lines.append("рџ•‹ РќР°РјР°Р·С‹")
    lines.extend(prayer_section)

    lines.append("\nрџ“– РљРѕСЂР°РЅ")
    lines.extend(quran_lines)

    lines.append("\nрџ”Ґ Critical Р·Р°РґР°С‡Рё")
    if critical_tasks:
        for t in critical_tasks:
            if t.planned_at:
                lines.append(f"вЂў #{t.id} {t.planned_at} вЂ” {t.title} [{t.status}]")
            else:
                lines.append(f"вЂў #{t.id} вЂ” {t.title} [{t.status}]")
    else:
        lines.append("вЂў РђРєС‚РёРІРЅС‹С… critical Р·Р°РґР°С‡ РЅРµС‚.")

    lines.append("\nрџ“Њ Р§С‚Рѕ РѕСЃС‚Р°Р»РѕСЃСЊ Р·Р°РєСЂС‹С‚СЊ СЃРµРіРѕРґРЅСЏ")
    if open_tasks:
        for t in open_tasks:
            if t.planned_at:
                lines.append(f"вЂў #{t.id} {t.planned_at} вЂ” {t.title} [{t.status}]")
            else:
                lines.append(f"вЂў #{t.id} вЂ” {t.title} [{t.status}]")
    else:
        lines.append("вЂў Р’СЃС‘ Р·Р°РєСЂС‹С‚Рѕ вњ…")

    if cfg.allowed_telegram_id:
        await bot.send_message(
            cfg.allowed_telegram_id,
            "\n".join(lines),
            reply_markup=followup_keyboard,
        )


async def fire_alert(alert_id: int, bot, scheduler) -> None:
    """
    Universal persistent alert executor.

    Supported:
    - prayer_reminder
    - boss_critical
    - quran_followup

    Atomic rule:
    - only one worker may claim the alert for firing
    - claimed alert moves to internal transient status "firing"
    - before send, handler checks that alert is still "firing"
    """
    Session = get_sessionmaker()

    async with Session() as session:
        alert = await crud.claim_alert_for_fire(session, alert_id=alert_id)
        if alert is None:
            log.info(
                "Skip fire_alert id=%s because alert already won by another path",
                alert_id,
            )
            return

        now = datetime.now(APP_TZ)

        if alert.alert_type == "prayer_reminder":
            is_stale = await _is_prayer_alert_stale(
                session=session,
                alert=alert,
                now=now,
            )
            if is_stale:
                payload = _load_payload(alert.payload_json)
                payload["stopped_reason"] = "stale_on_fire"
                await crud.finalize_firing_alert(
                    session,
                    alert_id=alert.id,
                    status="cancelled",
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
                return

        if alert.alert_type == "prayer_reminder":
            await _handle_prayer_reminder(
                session=session,
                alert=alert,
                bot=bot,
                scheduler=scheduler,
            )
        elif alert.alert_type == "boss_critical":
            await _handle_boss_critical(
                session=session,
                alert=alert,
                bot=bot,
                scheduler=scheduler,
            )
        elif alert.alert_type == "quran_followup":
            await _handle_quran_followup(
                session=session,
                alert=alert,
                bot=bot,
                scheduler=scheduler,
            )
        else:
            await crud.fail_alert_if_open(session, alert_id=alert.id)
            log.warning("Unknown alert_type=%s id=%s", alert.alert_type, alert.id)


async def _handle_prayer_reminder(session, alert: AlertQueue, bot, scheduler) -> None:
    payload = _load_payload(alert.payload_json)
    now = datetime.now(APP_TZ)

    chat_id = payload.get("chat_id")
    prayer_name = payload.get("prayer_name", "Prayer")
    repeat_count = int(payload.get("repeat_count", 0))
    max_repeats = int(
        payload.get(
            "max_repeats",
            (
                PRAYER_MAX_REPEATS_QUIET
                if prayer_name.lower() == "isha"
                else PRAYER_MAX_REPEATS_DEFAULT
            ),
        )
    )
    repeat_interval_min = alert.repeat_interval_min or PRAYER_REPEAT_INTERVAL_MIN

    if not chat_id:
        await crud.finalize_firing_alert(session, alert_id=alert.id, status="failed")
        log.warning("Prayer alert missing chat_id id=%s", alert.id)
        return

    if await _is_prayer_alert_stale(session=session, alert=alert, now=now):
        payload["stopped_reason"] = "stale_prayer_alert"
        await crud.finalize_firing_alert(
            session,
            alert_id=alert.id,
            status="cancelled",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        return

    prayer_times_service = PrayerTimesService(session)
    routine_service = RoutineService(
        session=session,
        prayer_times_service=prayer_times_service,
    )

    is_sleep_now = await routine_service.is_sleep_time(now)
    is_second_sleep_now = await routine_service.is_second_sleep(now)
    quiet_mode_now = is_sleep_now or is_second_sleep_now

    if quiet_mode_now:
        next_wake = await _find_next_wake_slot(routine_service, now)
        if next_wake is None or repeat_count >= max_repeats:
            payload["stopped_reason"] = "quiet_mode_limit"
            await crud.finalize_firing_alert(
                session,
                alert_id=alert.id,
                status="cancelled",
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            return

        payload["repeat_count"] = repeat_count + 1
        payload["quiet_mode_postpone"] = True

        success = await crud.reschedule_firing_alert(
            session,
            alert_id=alert.id,
            scheduled_for=next_wake,
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        if success:
            _schedule_same_alert(
                alert_id=alert.id,
                scheduled_for=next_wake,
                scheduler=scheduler,
                bot=bot,
            )
        return

    text = f"🕋 Напоминание о намазе: {prayer_name}\nВремя намаза уже наступило."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Намаз выполнен",
                    callback_data=f"prayer_done:{alert.id}",
                )
            ]
        ]
    )

    if not await _pre_send_idempotency_gate(
        session=session,
        alert_id=alert.id,
        alert_label="Prayer",
    ):
        return

    await bot.send_message(chat_id, text, reply_markup=keyboard)

    repeat_count += 1
    payload["repeat_count"] = repeat_count

    if repeat_count >= max_repeats:
        await crud.finalize_firing_alert(
            session,
            alert_id=alert.id,
            status="cancelled",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        return

    next_run = now + timedelta(minutes=repeat_interval_min)

    if await routine_service.is_sleep_time(
        next_run
    ) or await routine_service.is_second_sleep(next_run):
        next_wake = await _find_next_wake_slot(routine_service, next_run)
        if next_wake is None:
            await crud.finalize_firing_alert(
                session,
                alert_id=alert.id,
                status="cancelled",
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            return
        next_run = next_wake

    success = await crud.reschedule_firing_alert(
        session,
        alert_id=alert.id,
        scheduled_for=next_run,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    if success:
        _schedule_same_alert(
            alert_id=alert.id,
            scheduled_for=next_run,
            scheduler=scheduler,
            bot=bot,
        )


async def _handle_boss_critical(session, alert: AlertQueue, bot, scheduler) -> None:
    """
    Persistent escalation loop for boss critical tasks.
    """
    payload = _load_payload(alert.payload_json)
    now = datetime.now(APP_TZ)

    chat_id = payload.get("chat_id")
    if not chat_id:
        await crud.finalize_firing_alert(session, alert_id=alert.id, status="failed")
        return

    title = payload.get("boss_title") or payload.get("text") or "РЁРµС„ СЃСЂРѕС‡РЅРѕ: Р·Р°РґР°С‡Р°"
    repeat_count = int(payload.get("repeat_count", 0))
    max_repeats = int(payload.get("max_repeats", 20))
    repeat_interval_min = alert.repeat_interval_min or 15

    deadline_at = None
    raw_deadline = payload.get("deadline_at")
    if isinstance(raw_deadline, str) and raw_deadline.strip():
        try:
            deadline_at = datetime.fromisoformat(raw_deadline)
            if deadline_at.tzinfo is None:
                deadline_at = deadline_at.replace(tzinfo=APP_TZ)
            else:
                deadline_at = deadline_at.astimezone(APP_TZ)
        except Exception:
            deadline_at = None

    boss_service = BossPriorityService(session)
    decision = await boss_service.evaluate_task(
        title=title,
        now_dt=now,
        deadline_at=deadline_at,
    )

    payload["urgency_code"] = decision.urgency_code

    if repeat_count >= max_repeats:
        payload["stopped_reason"] = "max_repeats_reached"
        await crud.finalize_firing_alert(
            session,
            alert_id=alert.id,
            status="cancelled",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        return

    if not decision.should_wake_now:
        if decision.delayed_until is None:
            payload["stopped_reason"] = "no_wake_slot_found"
            await crud.finalize_firing_alert(
                session,
                alert_id=alert.id,
                status="cancelled",
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            return

        success = await crud.reschedule_firing_alert(
            session,
            alert_id=alert.id,
            scheduled_for=decision.delayed_until,
            repeat_interval_min=decision.repeat_interval_min or repeat_interval_min,
            priority=_priority_from_urgency(
                urgency_code=decision.urgency_code,
                is_critical=decision.is_critical,
            ),
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        if success:
            _schedule_same_alert(
                alert_id=alert.id,
                scheduled_for=decision.delayed_until,
                scheduler=scheduler,
                bot=bot,
            )
        return

        return

    text = _build_boss_runtime_message(
        title=title,
        urgency_code=decision.urgency_code,
        deadline_at=deadline_at,
        is_critical=decision.is_critical,
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="вњ… Critical Р·Р°РґР°С‡Р° РІС‹РїРѕР»РЅРµРЅР°",
                    callback_data=f"boss_done:{alert.id}",
                )
            ]
        ]
    )

    if not await _pre_send_idempotency_gate(
        session=session,
        alert_id=alert.id,
        alert_label="Boss",
    ):
        return

    await bot.send_message(chat_id, text, reply_markup=keyboard)

    repeat_count += 1
    payload["repeat_count"] = repeat_count
    payload["text"] = text

    if repeat_count >= max_repeats:
        await crud.finalize_firing_alert(
            session,
            alert_id=alert.id,
            status="cancelled",
            payload_json=json.dumps(payload, ensure_ascii=False),
        )
        return

    next_run = now + timedelta(minutes=repeat_interval_min)

    next_decision = await boss_service.evaluate_task(
        title=title,
        now_dt=next_run,
        deadline_at=deadline_at,
    )

    if not next_decision.should_wake_now and next_decision.delayed_until is not None:
        next_run = next_decision.delayed_until

    success = await crud.reschedule_firing_alert(
        session,
        alert_id=alert.id,
        scheduled_for=next_run,
        repeat_interval_min=next_decision.repeat_interval_min or repeat_interval_min,
        priority=_priority_from_urgency(
            urgency_code=next_decision.urgency_code,
            is_critical=next_decision.is_critical,
        ),
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    if success:
        _schedule_same_alert(
            alert_id=alert.id,
            scheduled_for=next_run,
            scheduler=scheduler,
            bot=bot,
        )


async def _handle_quran_followup(session, alert: AlertQueue, bot, scheduler) -> None:
    payload = _load_payload(alert.payload_json)
    chat_id = payload.get("chat_id")
    text = payload.get("text", "рџ“– РќР°РїРѕРјРёРЅР°РЅРёРµ РїРѕ РљРѕСЂР°РЅСѓ.")

    if not chat_id:
        await crud.finalize_firing_alert(session, alert_id=alert.id, status="failed")
        return

        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ“– Р”РѕС‡РёС‚Р°СЋ СЃРµР№С‡Р°СЃ",
                    callback_data=f"quran_followup:read_now:{alert.id}",
                ),
                InlineKeyboardButton(
                    text="рџ“€ РџРµСЂРµРЅРµСЃС‚Рё РЅР° Р·Р°РІС‚СЂР°",
                    callback_data=f"quran_followup:move_tomorrow:{alert.id}",
                ),
            ]
        ]
    )

    if not await _pre_send_idempotency_gate(
        session=session,
        alert_id=alert.id,
        alert_label="Quran followup",
    ):
        return

    await bot.send_message(chat_id, text, reply_markup=keyboard)

    await crud.activate_firing_alert(session, alert_id=alert.id)


def _build_prayer_reminder_at(
    *,
    prayer_name: str,
    target_date: date,
    prayer_time,
) -> datetime:
    if prayer_name.lower() == "dhuhr":
        return datetime.combine(target_date, DHUHR_REMINDER_AT, tzinfo=APP_TZ)

    prayer_at = datetime.combine(target_date, prayer_time, tzinfo=APP_TZ)
    return prayer_at - timedelta(minutes=PRAYER_REMINDER_BEFORE_MIN)


async def ensure_prayer_alerts_for_day(
    *,
    session,
    target_date: date,
    chat_id: int,
    scheduler,
    bot,
) -> list[int]:
    prayer_times_service = PrayerTimesService(session)
    prayer_times = await prayer_times_service.get_prayer_times(target_date)
    now = datetime.now(APP_TZ)

    prayer_points = [
        ("Fajr", prayer_times.fajr),
        ("Dhuhr", prayer_times.dhuhr),
        ("Asr", prayer_times.asr),
        ("Maghrib", prayer_times.maghrib),
        ("Isha", prayer_times.isha),
    ]

    created_ids: list[int] = []

    for prayer_name, prayer_time in prayer_points:
        entity_id = f"{target_date.isoformat()}:{prayer_name.lower()}"
        prayer_at = datetime.combine(target_date, prayer_time, tzinfo=APP_TZ)
        scheduled_for = _build_prayer_reminder_at(
            prayer_name=prayer_name,
            target_date=target_date,
            prayer_time=prayer_time,
        )

        if scheduled_for < now:
            next_prayer_name, next_prayer_at = await _resolve_current_or_next_prayer(
                session,
                now,
            )
            if next_prayer_name != prayer_name or next_prayer_at is None:
                existing = await crud.get_active_alert_by_key(
                    session,
                    alert_type="prayer_reminder",
                    entity_type="prayer",
                    entity_id=entity_id,
                )
                if existing is not None and scheduler is not None:
                    existing_scheduled_for = _ensure_app_tz(existing.scheduled_for)
                    if existing_scheduled_for >= now:
                        _schedule_same_alert(
                            alert_id=existing.id,
                            scheduled_for=existing_scheduled_for,
                            scheduler=scheduler,
                            bot=bot,
                        )
                continue
            scheduled_for = now + timedelta(seconds=RECOVERY_RESCHEDULE_DELAY_SEC)

        max_repeats = (
            PRAYER_MAX_REPEATS_QUIET
            if prayer_name.lower() == "isha"
            else PRAYER_MAX_REPEATS_DEFAULT
        )

        payload_json = json.dumps(
            {
                "chat_id": chat_id,
                "prayer_name": prayer_name,
                "repeat_count": 0,
                "max_repeats": max_repeats,
                "target_date": target_date.isoformat(),
                "prayer_at": prayer_at.isoformat(),
            },
            ensure_ascii=False,
        )

        alert = await crud.create_or_reuse_alert(
            session,
            alert_type="prayer_reminder",
            entity_type="prayer",
            entity_id=entity_id,
            scheduled_for=scheduled_for,
            repeat_interval_min=PRAYER_REPEAT_INTERVAL_MIN,
            priority=1000,
            payload_json=payload_json,
            status="pending",
        )

        created_ids.append(alert.id)

        if scheduler is not None:
            alert_scheduled_for = _ensure_app_tz(alert.scheduled_for)
            if alert_scheduled_for >= now:
                _schedule_same_alert(
                    alert_id=alert.id,
                    scheduled_for=alert_scheduled_for,
                    scheduler=scheduler,
                    bot=bot,
                )

    return created_ids


def _schedule_same_alert(
    alert_id: int,
    scheduled_for: datetime,
    scheduler,
    bot,
) -> None:
    from apscheduler.triggers.date import DateTrigger

    run_date = _ensure_app_tz(scheduled_for)

    scheduler.add_job(
        fire_alert,
        trigger=DateTrigger(run_date=run_date, timezone=APP_TZ),
        id=f"alert_{alert_id}",
        kwargs={
            "alert_id": alert_id,
            "bot": bot,
            "scheduler": scheduler,
        },
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=300,
    )


def _load_payload(payload_json: str | None) -> dict:
    if not payload_json:
        return {}

    try:
        data = json.loads(payload_json)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}

    return {}


async def _pre_send_idempotency_gate(
    *,
    session,
    alert_id: int,
    alert_label: str,
) -> bool:
    latest = await crud.get_alert(session, alert_id)
    terminal_block_statuses = {"completed", "cancelled", "expired"}

    if latest is None:
        log.info(
            "%s alert id=%s blocked by pre-send gate status=%s",
            alert_label,
            alert_id,
            None,
        )
        return False

    if latest.status in terminal_block_statuses or latest.status != "firing":
        log.info(
            "%s alert id=%s blocked by pre-send gate status=%s",
            alert_label,
            alert_id,
            latest.status,
        )
        return False
    return True

async def _find_next_wake_slot(
    routine_service: RoutineService,
    start_at: datetime,
) -> datetime | None:
    probe = start_at.replace(second=0, microsecond=0)
    limit = probe + timedelta(hours=12)

    while probe <= limit:
        in_primary_sleep = await routine_service.is_sleep_time(probe)
        in_second_sleep = await routine_service.is_second_sleep(probe)

        if not in_primary_sleep and not in_second_sleep:
            return probe

        probe += timedelta(minutes=15)

    return None


def _build_boss_runtime_message(
    *,
    title: str,
    urgency_code: str,
    deadline_at: datetime | None,
    is_critical: bool,
) -> str:
    if is_critical:
        header = "рџ”Ґ РЁРµС„: РљР РРўРР§Р•РЎРљРђРЇ Р·Р°РґР°С‡Р°"
    elif urgency_code == "critical":
        header = "рџ”Ґ РЁРµС„: РІС‹СЃРѕРєРёР№ СЂРёСЃРє РїСЂРѕСЃСЂРѕС‡РєРё"
    elif urgency_code == "high":
        header = "вљ пёЏ РЁРµС„: СЃСЂРѕС‡РЅР°СЏ Р·Р°РґР°С‡Р°"
    else:
        header = "рџ’ј РЁРµС„: Р·Р°РґР°С‡Р°"

    lines = [header, title]

    if deadline_at is not None:
        lines.append(
            f"Deadline: {deadline_at.astimezone(APP_TZ).strftime('%Y-%m-%d %H:%M')}"
        )

    lines.append(f"Urgency: {urgency_code}")
    lines.append("РџРѕРґС‚РІРµСЂРґРёС‚Рµ РІС‹РїРѕР»РЅРµРЅРёРµ РїРѕСЃР»Рµ Р·Р°РєСЂС‹С‚РёСЏ Р·Р°РґР°С‡Рё.")
    return "\n".join(lines)


def _priority_from_urgency(*, urgency_code: str, is_critical: bool) -> int:
    if is_critical or urgency_code == "critical":
        return 1000
    if urgency_code == "high":
        return 900
    return 800


async def _build_prayer_status_section(session) -> list[str]:
    today = datetime.now(APP_TZ).date()
    prayer_names = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    lines: list[str] = []

    for prayer_name in prayer_names:
        alert = await crud.get_latest_alert_by_entity(
            session,
            alert_type="prayer_reminder",
            entity_type="prayer",
            entity_id=f"{today.isoformat()}:{prayer_name.lower()}",
        )

        if alert is None:
            lines.append(f"вЂў {prayer_name}: РЅРµС‚ РґР°РЅРЅС‹С…")
            continue

        if alert.status == "done":
            lines.append(f"вЂў {prayer_name}: РїРѕРґС‚РІРµСЂР¶РґС‘РЅ вњ…")
        elif alert.status in ("pending", "active", "firing"):
            lines.append(f"вЂў {prayer_name}: РЅР°РїРѕРјРёРЅР°РЅРёРµ Р°РєС‚РёРІРЅРѕ вЏі")
        elif alert.status == "cancelled":
            lines.append(f"вЂў {prayer_name}: С†РёРєР» РѕСЃС‚Р°РЅРѕРІР»РµРЅ")
        else:
            lines.append(f"вЂў {prayer_name}: {alert.status}")

    return lines


async def _ensure_quran_followup_alert(
    *,
    session,
    chat_id: int,
    summary_text: str,
) -> int:
    today = datetime.now(APP_TZ).date()
    entity_id = today.isoformat()
    now = datetime.now(APP_TZ)

    alert = await crud.create_or_reuse_alert(
        session,
        alert_type="quran_followup",
        entity_type="quran_daily_goal",
        entity_id=entity_id,
        scheduled_for=now + timedelta(minutes=5),
        repeat_interval_min=None,
        priority=80,
        payload_json=json.dumps(
            {
                "chat_id": chat_id,
                "text": f"{summary_text}\n\nР’С‹Р±РµСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ:",
            },
            ensure_ascii=False,
        ),
        status="pending",
    )
    return alert.id


async def _is_prayer_alert_stale(
    *,
    session,
    alert: AlertQueue,
    now: datetime,
) -> bool:
    payload = _load_payload(alert.payload_json)
    prayer_name = (payload.get("prayer_name") or "").strip().lower()
    target_date_raw = payload.get("target_date")

    if not prayer_name or not target_date_raw:
        return False

    try:
        target_date = date.fromisoformat(target_date_raw)
    except Exception:
        return False

    prayer_times_service = PrayerTimesService(session)
    prayer_times = await prayer_times_service.get_prayer_times(target_date)

    prayer_points = [
        ("fajr", prayer_times.fajr),
        ("dhuhr", prayer_times.dhuhr),
        ("asr", prayer_times.asr),
        ("maghrib", prayer_times.maghrib),
        ("isha", prayer_times.isha),
    ]

    names = [name for name, _ in prayer_points]
    if prayer_name not in names:
        return False

    idx = names.index(prayer_name)

    if idx < len(prayer_points) - 1:
        _, next_time = prayer_points[idx + 1]
        next_prayer_at = datetime.combine(target_date, next_time, tzinfo=APP_TZ)
        next_prayer_reminder_at = _build_prayer_reminder_at(
            prayer_name=names[idx + 1],
            target_date=target_date,
            prayer_time=next_time,
        )
        return now >= next_prayer_reminder_at

    tomorrow = target_date + timedelta(days=1)
    tomorrow_times = await prayer_times_service.get_prayer_times(tomorrow)
    tomorrow_fajr_at = datetime.combine(tomorrow, tomorrow_times.fajr, tzinfo=APP_TZ)
    tomorrow_fajr_reminder_at = _build_prayer_reminder_at(
        prayer_name="fajr",
        target_date=tomorrow,
        prayer_time=tomorrow_times.fajr,
    )
    return now >= tomorrow_fajr_reminder_at


async def _resolve_current_or_next_prayer(
    session,
    now: datetime,
) -> tuple[str | None, datetime | None]:
    prayer_times_service = PrayerTimesService(session)

    for probe_date in (now.date(), now.date() + timedelta(days=1)):
        prayer_times = await prayer_times_service.get_prayer_times(probe_date)
        prayer_points = [
            ("Fajr", prayer_times.fajr),
            ("Dhuhr", prayer_times.dhuhr),
            ("Asr", prayer_times.asr),
            ("Maghrib", prayer_times.maghrib),
            ("Isha", prayer_times.isha),
        ]

        for prayer_name, prayer_time in prayer_points:
            prayer_at = datetime.combine(probe_date, prayer_time, tzinfo=APP_TZ)
            reminder_at = _build_prayer_reminder_at(
                prayer_name=prayer_name,
                target_date=probe_date,
                prayer_time=prayer_time,
            )

            if now <= prayer_at + timedelta(minutes=30):
                if now >= reminder_at or prayer_at >= now:
                    return prayer_name, prayer_at

    return None, None


def _ensure_app_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ)


