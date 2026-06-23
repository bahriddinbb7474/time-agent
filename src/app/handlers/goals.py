from __future__ import annotations

from collections import defaultdict

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.categories import TIME_GROUPS
from app.services.goal_service import (
    GoalNotFoundError,
    GoalService,
    GoalValidationError,
    VALID_GOAL_HORIZONS,
)


router = Router()

HORIZON_LABELS = {
    "daily": "Сегодня",
    "monthly": "Месяц",
    "six_month": "6 месяцев",
    "yearly": "Год",
}
STATUS_LABELS = {
    "active": "активна",
    "paused": "пауза",
    "done": "сделано",
}
TIME_GROUP_LABELS = {group.code: group.label for group in TIME_GROUPS}
GOAL_TIME_GROUP_CODES = tuple(
    group.code for group in TIME_GROUPS if group.code not in {"no_data", "waste"}
)


@router.message(Command("goals"))
async def goals_cmd(message: Message, session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    goals = await GoalService(session).list_goals(user_id=user_id)
    if not goals:
        await message.answer(
            "🎯 Цели пока пустые.\n"
            "Добавить: /goal_add daily quran Читать Коран minutes=30 priority=10"
        )
        return

    grouped = defaultdict(list)
    for goal in goals:
        grouped[goal.horizon].append(goal)

    lines = ["🎯 Цели"]
    for horizon in ("daily", "monthly", "six_month", "yearly"):
        items = grouped.get(horizon)
        if not items:
            continue
        lines.extend(["", f"{HORIZON_LABELS[horizon]}:"])
        for goal in items:
            suffix = _goal_suffix(goal)
            status = "" if goal.status == "active" else f" [{STATUS_LABELS[goal.status]}]"
            lines.append(f"{goal.id}. {goal.title}{suffix}{status}")

    await message.answer("\n".join(lines))


@router.message(Command("goal_add"))
async def goal_add_cmd(message: Message, session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    payload = (message.text or "").removeprefix("/goal_add").strip()
    parsed = _parse_goal_add_payload(payload)
    if parsed is None:
        await message.answer(_goal_add_help())
        return
    try:
        goal = await GoalService(session).create_goal(user_id=user_id, **parsed)
    except GoalValidationError as exc:
        await message.answer(f"❌ Цель не сохранена: {exc}\n\n{_goal_add_help()}")
        return

    await message.answer(f"✅ Цель добавлена: #{goal.id} — {goal.title}")


@router.message(Command("goal_archive"))
async def goal_archive_cmd(message: Message, session: AsyncSession) -> None:
    await _set_goal_status(message, session, action="archive")


@router.message(Command("goal_pause"))
async def goal_pause_cmd(message: Message, session: AsyncSession) -> None:
    await _set_goal_status(message, session, action="pause")


@router.message(Command("goal_done"))
async def goal_done_cmd(message: Message, session: AsyncSession) -> None:
    await _set_goal_status(message, session, action="done")


async def _set_goal_status(
    message: Message, session: AsyncSession, *, action: str
) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    goal_id = _parse_goal_id(message.text or "", command=f"/goal_{action}")
    if goal_id is None:
        await message.answer(f"Формат: /goal_{action} <id>")
        return

    service = GoalService(session)
    try:
        if action == "archive":
            goal = await service.archive_goal(user_id=user_id, goal_id=goal_id)
            label = "архивирована"
        elif action == "pause":
            goal = await service.pause_goal(user_id=user_id, goal_id=goal_id)
            label = "поставлена на паузу"
        else:
            goal = await service.mark_done(user_id=user_id, goal_id=goal_id)
            label = "закрыта"
    except GoalNotFoundError:
        await message.answer(f"Цель #{goal_id} не найдена.")
        return

    await message.answer(f"✅ Цель #{goal.id} {label}.")


def _parse_goal_add_payload(payload: str) -> dict | None:
    parts = payload.split()
    if len(parts) < 3:
        return None
    horizon = parts[0]
    time_group = parts[1]
    title_parts: list[str] = []
    options: dict[str, str] = {}
    for token in parts[2:]:
        if "=" in token:
            key, value = token.split("=", 1)
            options[key.strip().lower()] = value.strip()
        else:
            title_parts.append(token)
    title = " ".join(title_parts).strip()
    if not title:
        return None
    result: dict = {
        "horizon": horizon,
        "time_group": time_group,
        "title": title,
    }
    if "minutes" in options:
        minutes = _parse_positive_int(options["minutes"])
        if minutes is None:
            return None
        result["preferred_minutes_per_day"] = minutes
    if "priority" in options:
        priority = _parse_int(options["priority"])
        if priority is None:
            return None
        result["priority"] = priority
    return result


def _parse_goal_id(text: str, *, command: str) -> int | None:
    payload = text.removeprefix(command).strip()
    if not payload or not payload.isdigit():
        return None
    return int(payload)


def _parse_positive_int(value: str) -> int | None:
    parsed = _parse_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _goal_suffix(goal) -> str:
    parts: list[str] = []
    label = TIME_GROUP_LABELS.get(goal.time_group, goal.time_group)
    parts.append(label)
    if goal.preferred_minutes_per_day:
        parts.append(f"{goal.preferred_minutes_per_day} мин/день")
    if goal.target_value and goal.unit:
        parts.append(f"{goal.target_value:g} {goal.unit}")
    return " — " + ", ".join(parts) if parts else ""


def _goal_add_help() -> str:
    return (
        "Формат:\n"
        "/goal_add <horizon> <time_group> <title> [minutes=<n>] [priority=<n>]\n\n"
        "Примеры:\n"
        "/goal_add daily quran Читать Коран minutes=30 priority=10\n"
        "/goal_add monthly sport Снизить вес minutes=45\n"
        "/goal_add yearly ai_projects Большой ИИ-проект minutes=90\n\n"
        f"horizon: {', '.join(sorted(VALID_GOAL_HORIZONS))}\n"
        f"time_group: {', '.join(GOAL_TIME_GROUP_CODES)}"
    )


def _user_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user is not None else None
