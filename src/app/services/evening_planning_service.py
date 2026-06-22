from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.crisis_stack_service import CrisisStackService
from app.services.categories import TIME_GROUPS, normalize_activity_time_group
from app.services.daily_control_accounting_service import DailyControlAccounting


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
    targets_lines: Sequence[str] = field(default_factory=list)
    mirror_lines: Sequence[str] = field(default_factory=list)


def build_evening_planning_message(data: EveningPlanningInput) -> str:
    lines: list[str] = [
        "🕘 Вечерний план",
    ]

    _append_text_section(lines, "🪞 Итог 24 часов", data.mirror_lines)
    _append_text_section(lines, "🕋 Намазы", data.prayer_lines)
    _append_text_section(lines, "📖 Коран", data.quran_lines)
    _append_text_section(lines, "💧 Здоровье/сиям", data.health_lines)
    _append_text_section(lines, "🎯 Итог дня", data.targets_lines)

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


def build_evening_24_hour_lines(
    accounting: DailyControlAccounting,
    *,
    done_count: int | None = None,
    unfinished_count: int | None = None,
) -> list[str]:
    labels = {group.code: group.label for group in TIME_GROUPS}
    grouped: dict[str, float] = {}
    additional_no_data = 0.0

    for category, minutes in accounting.category_minutes.items():
        code = normalize_activity_time_group(category)
        if code == "waste":
            continue
        if code == "no_data":
            additional_no_data += minutes
            continue
        grouped[code] = grouped.get(code, 0.0) + minutes

    lines: list[str] = []
    for group in TIME_GROUPS:
        if group.code in {"no_data", "waste"}:
            continue
        minutes = grouped.get(group.code, 0.0)
        if minutes > 0:
            lines.append(f"{labels[group.code]}: {_format_minutes(minutes)}")

    if accounting.unknown_minutes > 0:
        lines.append(f"Не помню: {_format_minutes(accounting.unknown_minutes)}")

    no_data_minutes = accounting.no_data_minutes + additional_no_data
    unmarked_waste = max(
        0.0,
        accounting.category_minutes.get("waste", 0.0)
        - accounting.owner_marked_waste_minutes,
    )
    no_data_minutes += unmarked_waste
    if no_data_minutes > 0:
        lines.append(f"{labels['no_data']}: {_format_minutes(no_data_minutes)}")

    if accounting.protected_minutes > 0:
        lines.append(
            "Защищённые интервалы (план): "
            f"{_format_minutes(accounting.protected_minutes)}"
        )

    if accounting.owner_marked_waste_minutes > 0:
        lines.append(
            f"{labels['waste']}: "
            f"{_format_minutes(accounting.owner_marked_waste_minutes)}"
        )

    lines.extend(
        [
            "",
            "План:",
            f"⏱ Запланировано: {_format_minutes(accounting.planned_minutes)}",
            f"⏱ Подтверждено фактом: {_format_minutes(accounting.actual_minutes)}",
        ]
    )
    if done_count is not None:
        lines.append(f"✅ Сделано: {done_count}")
    if unfinished_count is not None:
        lines.append(f"❌ Не сделано по плану: {unfinished_count}")

    lines.extend(
        [
            "",
            "Совет:",
            _build_tomorrow_advice(
                accounting=accounting,
                grouped=grouped,
                no_data_minutes=no_data_minutes,
            ),
        ]
    )
    return lines


def _format_minutes(value: float) -> str:
    total = max(0, int(round(value)))
    hours, minutes = divmod(total, 60)
    if hours and minutes:
        return f"{hours}ч {minutes}м"
    if hours:
        return f"{hours}ч"
    return f"{minutes}м"


def _build_tomorrow_advice(
    *,
    accounting: DailyControlAccounting,
    grouped: dict[str, float],
    no_data_minutes: float,
) -> str:
    if no_data_minutes >= 120:
        return "Завтра чаще отвечай на check-in."
    if accounting.owner_marked_waste_minutes > 0:
        return "Завтра поставь защиту от отвлечений."
    if grouped.get("sport", 0.0) <= 0:
        return "Можно добавить короткую ходьбу."
    if (
        grouped.get("family_time", 0.0) <= 0
        and grouped.get("relationships", 0.0) <= 0
    ):
        return "Можно выделить время семье или близким."
    return "День хорошо покрыт, завтра выбери 2 главных блока."


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
