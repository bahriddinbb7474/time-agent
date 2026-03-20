import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.core.time import APP_TZ
from app.db import crud
from app.db.models import AlertQueue
from app.scheduler.jobs import (
    RECOVERY_RESCHEDULE_DELAY_SEC,
    ensure_prayer_alerts_for_day,
    evening_summary,
    fire_alert,
    morning_briefing,
    prayer_cache_job,
    family_daily_check_job,
)

log = logging.getLogger("time-agent.scheduler")


def build_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=APP_TZ)

    scheduler.add_job(
        morning_briefing,
        trigger=CronTrigger(hour=8, minute=30, timezone=APP_TZ),
        id="morning_briefing",
        args=[bot, scheduler],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        evening_summary,
        trigger=CronTrigger(hour=21, minute=0, timezone=APP_TZ),
        id="evening_summary",
        args=[bot],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        prayer_cache_job,
        trigger=CronTrigger(hour=3, minute=0, timezone=APP_TZ),
        id="prayer_cache_job",
        args=[bot, scheduler],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    scheduler.add_job(
        family_daily_check_job,
        trigger=CronTrigger(hour=9, minute=5, timezone=APP_TZ),
        id="family_daily_check",
        args=[bot],
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    log.info("Scheduler configured TZ=%s", APP_TZ)
    return scheduler


async def recover_alerts(
    *,
    scheduler: AsyncIOScheduler,
    session: AsyncSession,
    bot,
) -> None:
    """
    Restore alerts from SQLite alert_queue after restart.

    Rules:
    - open alerts are first normalized by integrity scan
    - stale prayer alerts are cancelled, not rescheduled
    - overdue alerts are actualized before scheduling
    - old quran followups from previous days are cancelled
    - interrupted "firing" alerts are reset safely
    - already delivered quran followups must not be resent after restart
    """
    cfg = load_config()
    now = datetime.now(APP_TZ)

    integrity_stats = await _run_queue_integrity_scan(session=session, now=now)
    log.info(
        "Queue integrity scan: duplicates_cancelled=%s broken_payload=%s normalized_firing=%s",
        integrity_stats["duplicates_cancelled"],
        integrity_stats["broken_payload"],
        integrity_stats["normalized_firing"],
    )

    if cfg.allowed_telegram_id:
        await ensure_prayer_alerts_for_day(
            session=session,
            target_date=now.date(),
            chat_id=cfg.allowed_telegram_id,
            scheduler=scheduler,
            bot=bot,
        )

    alerts = await crud.list_open_alerts(session)
    open_alert_ids = {a.id for a in alerts}
    _cleanup_orphan_alert_jobs(
        scheduler=scheduler,
        open_alert_ids=open_alert_ids,
    )
    restored = 0
    stale_prayer_names: list[str] = []

    for alert in alerts:
        if alert.scheduled_for is None:
            continue

        if alert.alert_type == "prayer_reminder":
            is_stale, prayer_name = await _cancel_stale_prayer_alert_if_needed(
                session=session,
                alert=alert,
                now=now,
            )
            if is_stale:
                _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert.id)
                if prayer_name:
                    stale_prayer_names.append(prayer_name)
                continue

        recovery_action = await _decide_recovery_action(
            session=session,
            alert=alert,
            now=now,
        )

        if recovery_action["action"] == "skip":
            continue

        if recovery_action["action"] == "cancel":
            payload = _load_payload(alert.payload_json)
            payload["stopped_reason"] = recovery_action["reason"]
            cancelled = await crud.cancel_alert_if_open(
                session,
                alert_id=alert.id,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            if cancelled:
                _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert.id)
            continue

        if recovery_action["action"] == "keep_active":
            _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert.id)
            continue

        run_date = recovery_action["run_date"]
        target_status = recovery_action["target_status"]

        if target_status == "pending":
            reset_ok = await crud.reset_alert_to_pending_for_recovery(
                session,
                alert_id=alert.id,
                scheduled_for=run_date,
            )
            if not reset_ok:
                continue
        elif target_status == "active":
            activated = await crud.activate_firing_alert(
                session,
                alert_id=alert.id,
            )
            if not activated:
                continue
            _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert.id)
            continue

        _schedule_alert_job(
            scheduler=scheduler,
            bot=bot,
            alert_id=alert.id,
            run_date=run_date,
        )
        restored += 1

    log.info("Recovered alerts from DB: %s", restored)

    if stale_prayer_names and cfg.allowed_telegram_id:
        latest_missed = stale_prayer_names[-1]
        current_name = await _resolve_current_or_next_prayer_name(
            session=session,
            now=now,
        )

        if current_name:
            text = (
                f"⚠️ Я был офлайн во время {latest_missed}.\n"
                f"Сейчас актуален {current_name}."
            )
        else:
            text = f"⚠️ Я был офлайн во время {latest_missed}."

        try:
            await bot.send_message(cfg.allowed_telegram_id, text)
        except Exception:
            log.exception("Failed to send recovery prayer message")


async def _run_queue_integrity_scan(
    *,
    session: AsyncSession,
    now: datetime,
) -> dict[str, int]:
    stats = {
        "duplicates_cancelled": 0,
        "broken_payload": 0,
        "normalized_firing": 0,
    }

    alerts = await crud.list_open_alerts(session)
    grouped: dict[tuple[str, str, str | None], list[AlertQueue]] = defaultdict(list)
    for alert in alerts:
        key = (alert.alert_type, alert.entity_type, alert.entity_id)
        grouped[key].append(alert)

    for key, items in grouped.items():
        if key[2] is None or len(items) <= 1:
            continue

        items_sorted = sorted(
            items,
            key=lambda a: (
                a.priority,
                a.created_at,
                a.id,
            ),
            reverse=True,
        )
        winner = items_sorted[0]

        for loser in items_sorted[1:]:
            payload = _load_payload(loser.payload_json)
            payload["stopped_reason"] = "startup_duplicate_scan"
            cancelled = await crud.cancel_alert_if_open(
                session,
                alert_id=loser.id,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            if cancelled:
                stats["duplicates_cancelled"] += 1

        if winner.status == "firing":
            if winner.alert_type == "quran_followup":
                activated = await crud.activate_firing_alert(
                    session,
                    alert_id=winner.id,
                )
                if activated:
                    stats["normalized_firing"] += 1
            else:
                reset_ok = await crud.reset_alert_to_pending_for_recovery(
                    session,
                    alert_id=winner.id,
                    scheduled_for=max(_ensure_app_tz(winner.scheduled_for), now),
                )
                if reset_ok:
                    stats["normalized_firing"] += 1

        if winner.payload_json:
            payload = _load_payload(winner.payload_json)
            if not payload:
                stats["broken_payload"] += 1

    return stats


async def _decide_recovery_action(
    *,
    session: AsyncSession,
    alert: AlertQueue,
    now: datetime,
) -> dict:
    run_date = _ensure_app_tz(alert.scheduled_for)

    if alert.alert_type == "quran_followup":
        if alert.entity_id and alert.entity_id < now.date().isoformat():
            return {
                "action": "cancel",
                "reason": "stale_quran_followup_after_restart",
            }

        if alert.status == "active":
            return {
                "action": "keep_active",
            }

        if alert.status == "firing":
            return {
                "action": "keep_active",
                "target_status": "active",
            }

        if run_date < now:
            return {
                "action": "schedule",
                "target_status": "pending",
                "run_date": now + timedelta(seconds=RECOVERY_RESCHEDULE_DELAY_SEC),
            }

        return {
            "action": "schedule",
            "target_status": "pending",
            "run_date": run_date,
        }

    if run_date < now:
        return {
            "action": "schedule",
            "target_status": "pending",
            "run_date": now + timedelta(seconds=RECOVERY_RESCHEDULE_DELAY_SEC),
        }

    if alert.status == "firing":
        return {
            "action": "schedule",
            "target_status": "pending",
            "run_date": run_date,
        }

    return {
        "action": "schedule",
        "target_status": "pending",
        "run_date": run_date,
    }


async def _cancel_stale_prayer_alert_if_needed(
    *,
    session: AsyncSession,
    alert: AlertQueue,
    now: datetime,
) -> tuple[bool, str | None]:
    payload = _load_payload(alert.payload_json)
    prayer_name = payload.get("prayer_name")

    target_date_raw = payload.get("target_date")
    if not target_date_raw:
        return False, prayer_name

    from app.services.prayer_times_service import PrayerTimesService

    try:
        target_date = datetime.fromisoformat(f"{target_date_raw}T00:00:00").date()
    except Exception:
        return False, prayer_name

    prayer_times_service = PrayerTimesService(session)
    prayer_times = await prayer_times_service.get_prayer_times(target_date)

    prayer_points = [
        ("fajr", prayer_times.fajr),
        ("dhuhr", prayer_times.dhuhr),
        ("asr", prayer_times.asr),
        ("maghrib", prayer_times.maghrib),
        ("isha", prayer_times.isha),
    ]

    normalized_name = (prayer_name or "").strip().lower()
    names = [name for name, _ in prayer_points]

    if normalized_name not in names:
        return False, prayer_name

    idx = names.index(normalized_name)

    if idx < len(prayer_points) - 1:
        _, next_time = prayer_points[idx + 1]
        next_prayer_at = datetime.combine(target_date, next_time, tzinfo=APP_TZ)
        next_reminder_at = next_prayer_at - timedelta(minutes=10)
        is_stale = now >= next_reminder_at
    else:
        tomorrow = target_date + timedelta(days=1)
        tomorrow_times = await prayer_times_service.get_prayer_times(tomorrow)
        tomorrow_fajr_at = datetime.combine(
            tomorrow,
            tomorrow_times.fajr,
            tzinfo=APP_TZ,
        )
        tomorrow_fajr_reminder_at = tomorrow_fajr_at - timedelta(minutes=10)
        is_stale = now >= tomorrow_fajr_reminder_at

    if not is_stale:
        return False, prayer_name

    payload["stopped_reason"] = "stale_after_restart"
    await crud.cancel_alert_if_open(
        session,
        alert_id=alert.id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )

    return True, prayer_name


async def _resolve_current_or_next_prayer_name(
    *,
    session: AsyncSession,
    now: datetime,
) -> str | None:
    from app.services.prayer_times_service import PrayerTimesService

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
            reminder_at = prayer_at - timedelta(minutes=10)

            if now <= prayer_at + timedelta(minutes=30):
                if now >= reminder_at or prayer_at >= now:
                    return prayer_name

    return None


def _schedule_alert_job(
    *,
    scheduler: AsyncIOScheduler,
    bot,
    alert_id: int,
    run_date: datetime,
) -> None:
    _remove_scheduled_alert_job(scheduler=scheduler, alert_id=alert_id)

    scheduler.add_job(
        fire_alert,
        trigger=DateTrigger(
            run_date=run_date,
            timezone=APP_TZ,
        ),
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
        pass



def _cleanup_orphan_alert_jobs(
    *,
    scheduler: AsyncIOScheduler,
    open_alert_ids: set[int],
) -> None:
    if scheduler is None:
        return

    for job in scheduler.get_jobs():
        job_id = job.id or ""
        if not job_id.startswith("alert_"):
            continue

        raw_id = job_id.removeprefix("alert_")
        if not raw_id.isdigit():
            continue

        alert_id = int(raw_id)
        if alert_id in open_alert_ids:
            continue

        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
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


def _ensure_app_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(APP_TZ)


