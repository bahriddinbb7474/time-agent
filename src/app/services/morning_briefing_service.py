from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.crisis_stack_service import CrisisStackService


@dataclass(slots=True)
class MorningBriefingInput:
    timed_tasks: Sequence = field(default_factory=list)
    floating_tasks: Sequence = field(default_factory=list)
    daily_plan_text: str | None = None
    later_count: int = 0
    google_today_lines: Sequence[str] = field(default_factory=list)
    prayer_lines: Sequence[str] = field(default_factory=list)
    quran_lines: Sequence[str] = field(default_factory=list)
    health_lines: Sequence[str] = field(default_factory=list)
    targets_lines: Sequence[str] = field(default_factory=list)


def build_morning_briefing_message(data: MorningBriefingInput) -> str:
    active_tasks = list(data.timed_tasks) + list(data.floating_tasks)
    lines: list[str] = ["🕗 Утро. План на сегодня"]

    _append_daily_plan_section(lines, data.daily_plan_text)
    _append_focus_section(lines, active_tasks)
    _append_task_section(
        lines,
        "📌 Сегодня",
        active_tasks,
        empty_text="• Активных задач нет.",
    )
    _append_text_section(lines, "🕋 Намаз / защита", data.prayer_lines)
    _append_text_section(
        lines,
        "📖 Коран / здоровье",
        list(data.quran_lines) + list(data.health_lines),
    )
    _append_text_section(lines, "🎯 Цели дня", data.targets_lines)
    _append_later_section(lines, data.later_count)

    return "\n".join(lines)


def _append_daily_plan_section(lines: list[str], plan_text: str | None) -> None:
    if not plan_text:
        return

    lines.append("")
    lines.append("Saved plan")
    lines.append(f"• {plan_text}")


def _append_focus_section(lines: list[str], tasks: Sequence) -> None:
    focus_task = CrisisStackService.select_focus_task(tasks)
    if focus_task is None:
        return

    urgent_count = len(CrisisStackService.urgent_tasks(tasks))

    lines.append("")
    lines.append("🧭 Фокус")
    if urgent_count >= CrisisStackService.CRISIS_URGENT_THRESHOLD:
        lines.append(f"• Есть {urgent_count} срочных. Первый мягкий фокус:")
    else:
        lines.append("• Один следующий шаг:")
    lines.append(f"• {_format_task(focus_task)}")


def _append_task_section(
    lines: list[str],
    title: str,
    tasks: Sequence,
    *,
    empty_text: str,
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


def _append_later_section(lines: list[str], later_count: int) -> None:
    lines.append("")
    lines.append("📝 На потом")
    if later_count <= 0:
        lines.append("• Пусто.")
        return

    lines.append(f"• {later_count} в inbox. Без давления: /backlog")


def _format_task(task) -> str:
    task_id = getattr(task, "id", None)
    title = getattr(task, "title", "")
    planned_at = getattr(task, "planned_at", None)

    prefix = f"#{task_id} " if task_id is not None else ""
    if planned_at:
        return f"{prefix}{planned_at} — {title}"
    return f"{prefix}{title}"
