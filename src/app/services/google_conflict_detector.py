from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

from app.core.time import APP_TZ
from app.integrations.google.dto import GoogleEventDTO
from app.services.prayer_protection import (
    intervals_overlap,
    iter_prayer_protected_windows,
)
from app.services.prayer_times_service import PrayerTimesDTO


@dataclass(frozen=True, slots=True)
class GoogleConflictDTO:
    kind: str
    label: str
    google_summary: str
    local_title: str | None = None
    prayer_name: str | None = None


def detect_google_conflicts(
    *,
    events: Sequence[GoogleEventDTO],
    local_tasks: Sequence,
    day: date,
    prayer_times: PrayerTimesDTO | None = None,
) -> list[GoogleConflictDTO]:
    conflicts: list[GoogleConflictDTO] = []
    task_intervals = [
        (task, start_at, start_at + timedelta(minutes=_task_duration(task)))
        for task in local_tasks
        if (start_at := _task_start(task, day=day)) is not None
    ]

    prayer_windows = (
        list(iter_prayer_protected_windows(day=day, prayer_times=prayer_times))
        if prayer_times is not None
        else []
    )

    for event in events:
        event_interval = _event_interval(event)
        if event_interval is None:
            continue

        event_start, event_end = event_interval
        summary = event.summary or "(no title)"

        for task, task_start, task_end in task_intervals:
            if intervals_overlap(event_start, event_end, task_start, task_end):
                conflicts.append(
                    GoogleConflictDTO(
                        kind="task_overlap",
                        label="Google event overlaps local task",
                        google_summary=summary,
                        local_title=getattr(task, "title", None),
                    )
                )

        for window in prayer_windows:
            if intervals_overlap(event_start, event_end, window.start, window.end):
                conflicts.append(
                    GoogleConflictDTO(
                        kind="prayer_overlap",
                        label="Google event overlaps prayer protection",
                        google_summary=summary,
                        prayer_name=window.prayer_name,
                    )
                )

    return conflicts


def format_google_conflict_lines(
    conflicts: Sequence[GoogleConflictDTO],
    *,
    limit: int = 5,
) -> list[str]:
    lines: list[str] = []
    for conflict in conflicts[:limit]:
        if conflict.kind == "task_overlap" and conflict.local_title:
            lines.append(f"• {conflict.google_summary} ↔ {conflict.local_title}")
            continue
        if conflict.kind == "prayer_overlap" and conflict.prayer_name:
            lines.append(f"• {conflict.google_summary} ↔ {conflict.prayer_name}")
            continue
        lines.append(f"• {conflict.google_summary}")

    remaining = len(conflicts) - len(lines)
    if remaining > 0:
        lines.append(f"• more: {remaining}")
    return lines


def _event_interval(event: GoogleEventDTO) -> tuple[datetime, datetime] | None:
    if event.status == "cancelled" or event.all_day:
        return None
    if event.start_at is None or event.end_at is None:
        return None
    return event.start_at.astimezone(APP_TZ), event.end_at.astimezone(APP_TZ)


def _task_start(task, *, day: date) -> datetime | None:
    planned_at = getattr(task, "planned_at", None)
    if planned_at is None:
        return None
    if isinstance(planned_at, datetime):
        return planned_at.astimezone(APP_TZ)
    if isinstance(planned_at, str):
        value = planned_at.strip()
        for fmt in ("%H:%M", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(value, fmt)
            except ValueError:
                continue
            if fmt == "%H:%M":
                return datetime.combine(day, parsed.time(), tzinfo=APP_TZ)
            return parsed.replace(tzinfo=APP_TZ)
    return None


def _task_duration(task) -> int:
    duration_min = getattr(task, "duration_min", 30)
    try:
        return max(1, int(duration_min))
    except (TypeError, ValueError):
        return 30
