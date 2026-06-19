from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import ActivityEntry, TimeBlock


UNACCOUNTED_CATEGORY = "unaccounted"


@dataclass(slots=True)
class DailyControlAccounting:
    usage_date: date
    planned_minutes: float
    actual_minutes: float
    plan_variance_minutes: float
    useful_outside_plan_minutes: float
    unaccounted_minutes: float
    no_data_minutes: float
    owner_marked_waste_minutes: float
    category_minutes: dict[str, float] = field(default_factory=dict)


def _local(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=APP_TZ)
    return value.astimezone(APP_TZ)


def _day_bounds(usage_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(usage_date, time.min, tzinfo=APP_TZ)
    return start, start + timedelta(days=1)


def _clipped_minutes(
    start_at: datetime, end_at: datetime, lower: datetime, upper: datetime
) -> float:
    start = max(_local(start_at), lower)
    end = min(_local(end_at), upper)
    return max(0.0, (end - start).total_seconds() / 60.0)


def _overlap_minutes(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> float:
    start = max(_local(left_start), _local(right_start))
    end = min(_local(left_end), _local(right_end))
    return max(0.0, (end - start).total_seconds() / 60.0)


class DailyControlAccountingService:
    """Read-only Stage 20.1 accounting; it never mutates plan or fact rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summarize(
        self, *, user_id: int, usage_date: date
    ) -> DailyControlAccounting:
        day_start, day_end = _day_bounds(usage_date)
        blocks = await self._time_blocks(user_id, day_start, day_end)
        entries = await self._activity_entries(user_id, day_start, day_end)

        planned_minutes = sum(
            _clipped_minutes(block.start_at, block.end_at, day_start, day_end)
            for block in blocks
        )
        actual_minutes = 0.0
        unaccounted_minutes = 0.0
        owner_marked_waste_minutes = 0.0
        useful_outside_plan_minutes = 0.0
        category_minutes: dict[str, float] = {}

        for entry in entries:
            clipped = _clipped_minutes(entry.start_at, entry.end_at, day_start, day_end)
            if clipped <= 0:
                continue
            actual_minutes += clipped
            category_minutes[entry.category] = (
                category_minutes.get(entry.category, 0.0) + clipped
            )
            if entry.category == UNACCOUNTED_CATEGORY:
                unaccounted_minutes += clipped
                continue
            if entry.waste_marked_by_owner and entry.owner_confirmed:
                owner_marked_waste_minutes += clipped
                continue

            entry_start = max(_local(entry.start_at), day_start)
            entry_end = min(_local(entry.end_at), day_end)
            planned_overlap = sum(
                _overlap_minutes(
                    entry_start,
                    entry_end,
                    max(_local(block.start_at), day_start),
                    min(_local(block.end_at), day_end),
                )
                for block in blocks
            )
            useful_outside_plan_minutes += max(0.0, clipped - planned_overlap)

        day_minutes = (day_end - day_start).total_seconds() / 60.0
        no_data_minutes = max(0.0, day_minutes - actual_minutes)
        return DailyControlAccounting(
            usage_date=usage_date,
            planned_minutes=planned_minutes,
            actual_minutes=actual_minutes,
            plan_variance_minutes=actual_minutes - planned_minutes,
            useful_outside_plan_minutes=useful_outside_plan_minutes,
            unaccounted_minutes=unaccounted_minutes,
            no_data_minutes=no_data_minutes,
            owner_marked_waste_minutes=owner_marked_waste_minutes,
            category_minutes=category_minutes,
        )

    async def _time_blocks(
        self, user_id: int, day_start: datetime, day_end: datetime
    ) -> list[TimeBlock]:
        result = await self.session.execute(
            select(TimeBlock).where(
                TimeBlock.user_id == user_id,
                TimeBlock.status != "cancelled",
                TimeBlock.start_at < day_end,
                TimeBlock.end_at > day_start,
            )
        )
        return list(result.scalars().all())

    async def _activity_entries(
        self, user_id: int, day_start: datetime, day_end: datetime
    ) -> list[ActivityEntry]:
        result = await self.session.execute(
            select(ActivityEntry).where(
                ActivityEntry.user_id == user_id,
                ActivityEntry.start_at < day_end,
                ActivityEntry.end_at > day_start,
            )
        )
        return list(result.scalars().all())
