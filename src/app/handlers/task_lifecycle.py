from __future__ import annotations

import re
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.services.categories import KNOWN_CATEGORIES
from app.services.crisis_stack_service import CrisisStackService
from app.services.daily_plan_service import DailyPlanService
from app.services.task_create_service import TaskCreateService
from app.services.task_service import TaskService
from app.services.validation_result import ConflictType

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


def _format_edit_result_message(result) -> str:
    validation_result = result.validation_result
    if (
        validation_result is not None
        and validation_result.conflict_type == ConflictType.PRAYER
    ):
        base = validation_result.message or result.user_message
        return (
            f"⚠️ {base}\n"
            "Задача не изменена. Новое время нужно подтвердить через /edit."
        )

    return result.user_message


def _format_focus_task(task) -> str:
    return f"Фокус: #{task.id} — {task.title}\nСейчас делай это."


def _format_crisis_stack(tasks) -> str:
    urgent_tasks = CrisisStackService.urgent_tasks(tasks)
    ordered_tasks = CrisisStackService.order_focus_tasks(urgent_tasks)
    focus_task = ordered_tasks[0]

    lines = [
        f"Срочных задач: {len(urgent_tasks)}.",
        f"Фокус: #{focus_task.id} — {focus_task.title}",
    ]

    if len(ordered_tasks) > 1:
        lines.append("Дальше:")
        for task in ordered_tasks[1:5]:
            lines.append(f"• #{task.id} — {task.title}")

    return "\n".join(lines)


def _format_next_focus_line(task) -> str | None:
    if task is None:
        return None
    return f"Следующий фокус: #{task.id} — {task.title}"


async def _build_done_message(*, session: AsyncSession, task_id: int) -> str:
    tasks = await TaskService(session).list_active_focus_candidates()
    focus_task = CrisisStackService.select_focus_task(tasks)
    next_focus_line = _format_next_focus_line(focus_task)

    if next_focus_line is None:
        return f"Готово: #{task_id}"

    return f"Готово: #{task_id}\n{next_focus_line}"


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

    task_create_service = TaskCreateService(
        session=session,
        scheduler=scheduler,
        bot=message.bot,
    )

    result = await task_create_service.update_task(
        task_id=task_id,
        title=title,
        planned_at=planned_at,
        duration_min=duration,
        category=category,
        user_id=message.from_user.id if message.from_user else None,
    )

    await message.answer(_format_edit_result_message(result))


@router.message(Command("done"))
async def done_cmd(message: Message, session: AsyncSession):
    payload = message.text.removeprefix("/done").strip()

    if not payload or not ID_RE.match(payload):
        await message.answer("Формат: /done 12")
        return

    task_id = int(payload)
    task = await TaskService(session).mark_done(task_id)

    if task is None:
        await message.answer(f"Задача #{task_id} не найдена.")
        return

    await message.answer(await _build_done_message(session=session, task_id=task.id))


@router.message(Command("focus"))
async def focus_cmd(message: Message, session: AsyncSession):
    tasks = await TaskService(session).list_active_focus_candidates()
    focus_task = CrisisStackService.select_focus_task(tasks)

    if focus_task is None:
        await message.answer("Фокус пуст.")
        return

    await message.answer(_format_focus_task(focus_task))


@router.message(Command("crisis"))
async def crisis_cmd(message: Message, session: AsyncSession):
    tasks = await TaskService(session).list_active_focus_candidates()

    if not CrisisStackService.is_crisis(tasks):
        await message.answer("Кризиса нет. Попробуй /focus.")
        return

    await message.answer(_format_crisis_stack(tasks))


@router.message(Command("later"))
async def later_cmd(message: Message, session: AsyncSession):
    payload = message.text.removeprefix("/later").strip()

    if not payload:
        await message.answer("Формат: /later текст")
        return

    task = await TaskService(session).create_later(payload)
    await message.answer(f"На потом: #{task.id}")


@router.message(Command("backlog"))
async def backlog_cmd(message: Message, session: AsyncSession):
    items = await TaskService(session).list_later(limit=20)

    if not items:
        await message.answer("На потом пусто.")
        return

    lines = ["На потом:"]
    for item in items:
        lines.append(f"#{item.id} — {item.title}")

    await message.answer("\n".join(lines))


@router.message(Command("boss"))
async def boss_cmd(message: Message, session: AsyncSession):
    payload = message.text.removeprefix("/boss").strip()

    if not payload:
        await message.answer("Формат: /boss текст")
        return

    task = await TaskService(session).create_task(
        title=f"Шеф: {payload}",
        planned_at=None,
        duration_min=30,
        category="work",
        priority_code="BOSS_CRITICAL",
        user_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(f"Boss задача: #{task.id}")


@router.message(Command("plan_tomorrow"))
async def plan_tomorrow_cmd(message: Message, session: AsyncSession):
    payload = message.text.removeprefix("/plan_tomorrow").strip()

    if not payload:
        await message.answer("Формат: /plan_tomorrow текст")
        return

    plan_date = now_tz().date() + timedelta(days=1)
    await DailyPlanService(session).save_plan(plan_date=plan_date, text=payload)
    await message.answer("План на завтра сохранён.")


@router.callback_query(F.data.startswith("task_done:"))
async def task_done_callback(callback: CallbackQuery, session: AsyncSession):
    raw_task_id = (callback.data or "").removeprefix("task_done:")
    if not ID_RE.match(raw_task_id):
        await callback.answer("Неверный ID", show_alert=True)
        return

    task_id = int(raw_task_id)
    task = await TaskService(session).mark_done(task_id)
    if task is None:
        await callback.answer("Задача не найдена", show_alert=True)
        return

    await callback.answer(f"Готово: #{task.id}")
    if callback.message is not None:
        await callback.message.answer(
            await _build_done_message(session=session, task_id=task.id)
        )


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

    task_create_service = TaskCreateService(
        session=session,
        scheduler=scheduler,
        bot=message.bot,
    )

    result = await task_create_service.delete_task(task_id=task_id)

    await message.answer(result.user_message)

