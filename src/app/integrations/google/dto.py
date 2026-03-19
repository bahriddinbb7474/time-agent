from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class GoogleEventDTO:
    external_id: str
    calendar_id: str
    summary: str
    description: str
    start_at: datetime | None
    end_at: datetime | None
    all_day: bool
    status: str
    updated_at: datetime | None
    html_link: str | None
    local_task_id: int | None
    source_marker: str | None


@dataclass(slots=True)
class GoogleConflictItemDTO:
    task_id: int
    summary: str
    start_at_text: str
    conflict_label: str
    conflict_message: str
    has_safe_slot: bool


@dataclass(slots=True)
class GooglePullSummaryDTO:
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    skipped_echo: int = 0
    conflicts_total: int = 0
    conflicts_sleep: int = 0
    conflicts_prayer: int = 0
    notes: list[str] = field(default_factory=list)
    conflict_items: list[GoogleConflictItemDTO] = field(default_factory=list)

    def to_user_text(self) -> str:
        lines = [
            "✅ Google pull завершён.",
            f"imported: {self.imported}",
            f"updated: {self.updated}",
            f"skipped: {self.skipped}",
            f"skipped_echo: {self.skipped_echo}",
            f"conflicts: {self.conflicts_total}",
        ]

        if self.conflicts_total:
            lines.append(
                f"sleep_conflicts: {self.conflicts_sleep}, "
                f"prayer_conflicts: {self.conflicts_prayer}"
            )

        if self.conflict_items:
            lines.append(f"actionable_conflicts: {len(self.conflict_items)}")

        if self.notes:
            lines.append("")
            lines.append("Детали:")
            lines.extend(self.notes[:10])

        return "\n".join(lines)
