"""Stage 20.2-D proposal formatter tests. No runtime wiring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.services.schedule_proposal_builder import ScheduleProposal, UnscheduledItem
from app.services.schedule_proposal_formatter import (
    MAX_SUMMARY_LINES,
    format_schedule_proposal,
)


TZ = timezone(timedelta(hours=5))


@dataclass
class _Schedule:
    version: int = 1


@dataclass
class _Block:
    start_at: datetime
    end_at: datetime
    title: str
    block_type: str


def _proposal(blocks, unscheduled=()) -> ScheduleProposal:
    return ScheduleProposal(
        proposal_type="daily_schedule_draft",
        usage_date=date(2026, 6, 20),
        user_id=123,
        timezone="Asia/Tashkent",
        schedule=_Schedule(),  # type: ignore[arg-type]
        blocks=tuple(blocks),  # type: ignore[arg-type]
        unscheduled_items=tuple(unscheduled),
    )


def _block(hour: int, block_type: str, title: str) -> _Block:
    start = datetime(2026, 6, 20, hour % 24, tzinfo=TZ)
    return _Block(start, start + timedelta(minutes=30), title, block_type)


def test_summary_is_compact_and_reports_protection_and_overload() -> None:
    proposal = _proposal(
        [
            _block(0, "sleep", "Private sleep detail"),
            _block(5, "prayer", "Fajr"),
            _block(9, "task", "Focused work"),
            _block(10, "target", "English"),
            _block(11, "buffer", "Buffer"),
        ],
        [
            UnscheduledItem(
                item=None,
                reason="overload",
                title="Hidden private task",
                source_type="task",
            )
        ],
    )
    text = format_schedule_proposal(proposal)
    lines = text.splitlines()

    assert len(lines) <= MAX_SUMMARY_LINES
    assert "Защищено: сон 1, намаз 1" in text
    assert "Focused work" in text
    assert "English" in text
    assert "Не запланировано: 1" in text
    assert "Private sleep detail" not in text
    assert "Hidden private task" not in text


def test_summary_never_exceeds_fifteen_lines_and_truncates_titles() -> None:
    blocks = [
        _block(hour, "task", f"Task {hour} " + "x" * 100)
        for hour in range(20)
    ]
    lines = format_schedule_proposal(_proposal(blocks)).splitlines()
    assert len(lines) <= 15
    assert any("…" in line for line in lines)


def test_empty_summary_is_honest() -> None:
    text = format_schedule_proposal(_proposal([]))
    assert "Задач с явным временем пока нет" in text


def main() -> None:
    test_summary_is_compact_and_reports_protection_and_overload()
    test_summary_never_exceeds_fifteen_lines_and_truncates_titles()
    test_empty_summary_is_honest()
    print("PASS: schedule proposal formatter is concise and privacy-aware")


if __name__ == "__main__":
    main()
