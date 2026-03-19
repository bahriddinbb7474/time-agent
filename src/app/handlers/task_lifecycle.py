from __future__ import annotations

import re
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.services.crisis_stack_service import CrisisStackService
from app.services.google_calendar_service import GoogleCalendarService
from app.services.task_sync_service import TaskSyncService
from app.services.task_sync_policy_service import KNOWN_CATEGORIES

router = Router()

TIME_COLON_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2}):(?P<m>\d{2})(?!\d)")
TIME_SPACE_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2})\s+(?P<m>\d{2})(?!\d)")
TIME_DASH_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2})-(?P<m>\d{2})(?!\d)")
TIME_COMPACT_RE = re.compile(r"(?<!\d)(?P<hhmm>\d{4})(?!\d)")
DUR_RE = re.compile(r"\b(?P<dur>\d{1,3})\b$")
REMINDER_LIKE_RE = re.compile("\u043d\u0430\u043f\u043e\u043c\u043d|remind|reminder|\U0001F514", flags=re.IGNORECASE)
ID_RE = re.compile(r"^\d+$")


def _extract_time_token(raw: str) -> tuple[int, int, str] | None:
    def _valid(h: int, m: int) -> bool:
        return 0 <= h <= 23 and 0 <= m <= 59

    m_colon = TIME_COLON_RE.search(raw)
    if m_colon:
        h = int(m_colon.group("h"))
        m = int(m_colon.group("m"))
        if _valid(h, m):
            return h, m, m_colon.group(0)

    m_space = TIME_SPACE_RE.search(raw)
    if m_space:
        h = int(m_space.group("h"))
        m = int(m_space.group("m"))
        if _valid(h, m):
            return h, m, m_space.group(0)

    m_dash = TIME_DASH_RE.search(raw)
    if m_dash:
        h = int(m_dash.group("h"))
        m = int(m_dash.group("m"))
        if _valid(h, m):
            return h, m, m_dash.group(0)

    m_compact = TIME_COMPACT_RE.search(raw)
    if m_compact:
        token = m_compact.group("hhmm")
        h = int(token[:2])
        m = int(token[2:])
        if _valid(h, m):
            return h, m, token

    return None


def _use_short_timed_default_duration(*, title: str) -> bool:
    if CrisisStackService.is_urgent_text(title):
        return True

    return REMINDER_LIKE_RE.search(title or "") is not None


def parse_task_payload(text: str) -> tuple[str, str, datetime | None, int]:
    raw = text.strip()

    category = "personal"
    parts = raw.split(maxsplit=1)
    if parts and parts[0].lower() in KNOWN_CATEGORIES:
        category = parts[0].lower()
        raw = parts[1].strip() if len(parts) > 1 else ""

    time_token = _extract_time_token(raw)
    planned_at = None

    if time_token:
        h, m, matched_token = time_token

        base = now_tz().date()
        raw_lower = raw.lower()

        if "завтра" in raw_lower:
            base = base + timedelta(days=1)
            raw = re.sub(r"\bзавтра\b", "", raw, flags=re.IGNORECASE)
        elif "сегодня" in raw_lower:
            raw = re.sub(r"\bсегодня\b", "", raw, flags=re.IGNORECASE)

        raw = re.sub(r"\s+", " ", raw.replace(matched_token, "", 1)).strip()

        planned_at = datetime(
            year=base.year,
            month=base.month,
            day=base.day,
            hour=h,
            minute=m,
            tzinfo=APP_TZ,
        )

    duration = 30
    m_d = DUR_RE.search(raw)
    if m_d:
        duration = int(m_d.group("dur"))
        raw = raw[: m_d.start()].strip()

    title = re.sub(r"\s+", " ", raw).strip()

    if not title:
        title = "\u0417\u0430\u0434\u0430\u0447\u0430"

    if planned_at is not None and m_d is None and _use_short_timed_default_duration(title=title):
        duration = 15

    return category, title, planned_at, duration


@router.message(Command("edit"))
async def edit_cmd(
    message: Message,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    payload = message.text.removeprefix("/edit").strip()

    if not payload:
        await message.answer(
            "Формат: /edit 12 work Встреча завтра 14:00 40\n"
            "Категории: work, family, health, prayer, personal, other"
        )
        return

    parts = payload.split(maxsplit=1)
    if not parts or not ID_RE.match(parts[0]):
        await message.answer("Формат: /edit 12 work Встреча завтра 14:00 40")
        return

    task_id = int(parts[0])

    if len(parts) == 1:
        await message.answer(
            "После ID нужно указать новые данные задачи.\n"
            "Пример: /edit 12 work Встреча завтра 14:00 40"
        )
        return

    edit_payload = parts[1].strip()
    category, title, planned_at, duration = parse_task_payload(edit_payload)

    async def bot_notify_fn(*_args, **_kwargs):
        return None

    gcal_service = GoogleCalendarService(
        session_factory=lambda: session,
        bot_notify_fn=bot_notify_fn,
    )

    sync_service = TaskSyncService(
        session=session,
        gcal_service=gcal_service,
        scheduler=scheduler,
        bot=message.bot,
    )

    result = await sync_service.sync_update_task(
        task_id=task_id,
        title=title,
        planned_at=planned_at,
        duration_min=duration,
        category=category,
        user_id=message.from_user.id if message.from_user else None,
    )

    await message.answer(result.user_message)


@router.message(Command("delete"))
async def delete_cmd(
    message: Message,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    payload = message.text.removeprefix("/delete").strip()

    if not payload or not ID_RE.match(payload):
        await message.answer("Формат: /delete 12")
        return

    task_id = int(payload)

    async def bot_notify_fn(*_args, **_kwargs):
        return None

    gcal_service = GoogleCalendarService(
        session_factory=lambda: session,
        bot_notify_fn=bot_notify_fn,
    )

    sync_service = TaskSyncService(
        session=session,
        gcal_service=gcal_service,
        scheduler=scheduler,
        bot=message.bot,
    )

    result = await sync_service.sync_delete_task(task_id=task_id)

    await message.answer(result.user_message)

