from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.crisis_stack_service import CrisisStackService


@dataclass(slots=True)
class EveningPlanningInput:
    done_today: Sequence = field(default_factory=list)
    unfinished_tasks: Sequence = field(default_factory=list)
    later_items: Sequence = field(default_factory=list)
    tomorrow_tasks: Sequence = field(default_factory=list)
    prayer_lines: Sequence[str] = field(default_factory=list)
    quran_lines: Sequence[str] = field(default_factory=list)
    health_lines: Sequence[str] = field(default_factory=list)
    google_tomorrow_lines: Sequence[str] = field(default_factory=list)


def build_evening_planning_message(data: EveningPlanningInput) -> str:
    lines: list[str] = [
        "🕘 Вечерний план",
    ]

    _append_text_section(lines, "🕋 Намазы", data.prayer_lines)
    _append_text_section(lines, "📖 Коран", data.quran_lines)
    _append_text_section(lines, "💧 Здоровье/сиям", data.health_lines)

    _append_done_today_section(lines, data.done_today)
    _append_focus_section(lines, data.unfinished_tasks)
    _append_task_section(
        lines,
        "📌 Осталось сегодня",
        data.unfinished_tasks,
        empty_text="• Активных задач нет.",
    )
    _append_task_section(
        lines,
        "📝 На потом",
        data.later_items,
        empty_text="• Пусто.",
        footer="Посмотреть всё: /backlog",
    )
    _append_task_section(
        lines,
        "📅 Завтра",
        data.tomorrow_tasks,
        empty_text="• Локальных задач на завтра нет.",
    )

    lines.extend(["", "Что главное завтра?"])
    return "\n".join(lines)


def _append_done_today_section(lines: list[str], tasks: Sequence, limit: int = 5) -> None:
    lines.append("")
    lines.append("Done today")
    if not tasks:
        lines.append("• 0")
        return

    lines.append(f"• count: {len(tasks)}")
    for task in list(tasks)[:limit]:
        lines.append(f"• {_format_task(task)}")
    if len(tasks) > limit:
        lines.append(f"• more: {len(tasks) - limit}")


def _append_text_section(
    lines: list[str],
    title: str,
    values: Sequence[str],
) -> None:
    if not values:
        return

    lines.append("")
    lines.append(title)
    lines.extend(values)


def _append_focus_section(lines: list[str], tasks: Sequence) -> None:
    if not tasks:
        return

    focus_task = CrisisStackService.select_focus_task(tasks)
    if focus_task is None:
        return

    urgent_count = len(CrisisStackService.urgent_tasks(tasks))

    lines.append("")
    lines.append("🧭 Фокус")
    if urgent_count >= CrisisStackService.CRISIS_URGENT_THRESHOLD:
        lines.append(f"• Кризис: {urgent_count} срочных. Первый фокус:")
    else:
        lines.append("• Следующий фокус:")
    lines.append(f"• {_format_task(focus_task)}")


def _append_task_section(
    lines: list[str],
    title: str,
    tasks: Sequence,
    *,
    empty_text: str,
    footer: str | None = None,
    limit: int = 5,
) -> None:
    lines.append("")
    lines.append(title)

    if not tasks:
        lines.append(empty_text)
        return

    for task in list(tasks)[:limit]:
        lines.append(f"• {_format_task(task)}")

    if len(tasks) > limit:
        lines.append(f"• Ещё: {len(tasks) - limit}")

    if footer:
        lines.append(f"• {footer}")


def _format_task(task) -> str:
    task_id = getattr(task, "id", None)
    title = getattr(task, "title", "")
    planned_at = getattr(task, "planned_at", None)

    prefix = f"#{task_id} " if task_id is not None else ""
    if planned_at:
        return f"{prefix}{planned_at} — {title}"
    return f"{prefix}{title}"
