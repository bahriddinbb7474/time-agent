from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import ActivityEntry, Checkin, DailySchedule, TimeBlock


UNACCOUNTED_CATEGORY = "unaccounted"


@dataclass(slots=True)
class DailyControlAccounting:
    usage_date: date
    total_minutes: float
    planned_minutes: float
    actual_minutes: float
    plan_variance_minutes: float
    useful_outside_plan_minutes: float
    unaccounted_minutes: float
    no_data_minutes: float
    unknown_minutes: float
    protected_minutes: float
    owner_marked_waste_minutes: float
    aligned_checkins: int = 0
    unknown_checkins: int = 0
    deferred_checkins: int = 0
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


Interval = tuple[datetime, datetime]


def _clipped_interval(
    start_at: datetime, end_at: datetime, lower: datetime, upper: datetime
) -> Interval | None:
    start = max(_local(start_at), lower)
    end = min(_local(end_at), upper)
    return (start, end) if end > start else None


def _merge_intervals(intervals: list[Interval]) -> list[Interval]:
    if not intervals:
        return []
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _interval_minutes(intervals: list[Interval]) -> float:
    return sum((end - start).total_seconds() / 60.0 for start, end in intervals)


def _subtract_intervals(
    intervals: list[Interval], blockers: list[Interval]
) -> list[Interval]:
    result: list[Interval] = []
    merged_blockers = _merge_intervals(blockers)
    for start, end in _merge_intervals(intervals):
        fragments = [(start, end)]
        for blocker_start, blocker_end in merged_blockers:
            next_fragments: list[Interval] = []
            for fragment_start, fragment_end in fragments:
                if blocker_end <= fragment_start or blocker_start >= fragment_end:
                    next_fragments.append((fragment_start, fragment_end))
                    continue
                if blocker_start > fragment_start:
                    next_fragments.append((fragment_start, blocker_start))
                if blocker_end < fragment_end:
                    next_fragments.append((blocker_end, fragment_end))
            fragments = next_fragments
            if not fragments:
                break
        result.extend(fragments)
    return _merge_intervals(result)


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
        protected_blocks = await self._protected_blocks(user_id, day_start, day_end)
        entries = await self._activity_entries(user_id, day_start, day_end)
        checkins = await self._checkins(user_id, usage_date, day_start, day_end)
        unknown_checkins = await self._unknown_checkins(user_id, day_start, day_end)

        confirmed_entries = [entry for entry in entries if entry.owner_confirmed]
        activity_intervals = _merge_intervals(
            [
                interval
                for entry in confirmed_entries
                if (
                    interval := _clipped_interval(
                        entry.start_at, entry.end_at, day_start, day_end
                    )
                )
                is not None
            ]
        )
        unknown_intervals = _subtract_intervals(
            [
                interval
                for row in unknown_checkins
                if (
                    interval := _clipped_interval(
                        row.window_start, row.window_end, day_start, day_end
                    )
                )
                is not None
            ],
            activity_intervals,
        )
        protected_intervals = _subtract_intervals(
            [
                interval
                for block in protected_blocks
                if (
                    interval := _clipped_interval(
                        block.start_at, block.end_at, day_start, day_end
                    )
                )
                is not None
            ],
            activity_intervals + unknown_intervals,
        )

        planned_minutes = sum(
            _clipped_minutes(block.start_at, block.end_at, day_start, day_end)
            for block in blocks
        )
        actual_minutes = _interval_minutes(activity_intervals)
        unaccounted_minutes = 0.0
        owner_marked_waste_minutes = 0.0
        useful_outside_plan_minutes = 0.0
        category_minutes: dict[str, float] = {}

        for entry in confirmed_entries:
            clipped = _clipped_minutes(entry.start_at, entry.end_at, day_start, day_end)
            if clipped <= 0:
                continue
            category_minutes[entry.category] = (
                category_minutes.get(entry.category, 0.0) + clipped
            )
            if entry.category == UNACCOUNTED_CATEGORY:
                unaccounted_minutes += clipped
                continue
            if (
                entry.category == "waste"
                and entry.waste_marked_by_owner
                and entry.owner_confirmed
            ):
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
        unknown_minutes = _interval_minutes(unknown_intervals)
        protected_minutes = _interval_minutes(protected_intervals)
        no_data_minutes = max(
            0.0,
            day_minutes - actual_minutes - unknown_minutes - protected_minutes,
        )
        return DailyControlAccounting(
            usage_date=usage_date,
            total_minutes=day_minutes,
            planned_minutes=planned_minutes,
            actual_minutes=actual_minutes,
            plan_variance_minutes=actual_minutes - planned_minutes,
            useful_outside_plan_minutes=useful_outside_plan_minutes,
            unaccounted_minutes=unaccounted_minutes,
            no_data_minutes=no_data_minutes,
            unknown_minutes=unknown_minutes,
            protected_minutes=protected_minutes,
            owner_marked_waste_minutes=owner_marked_waste_minutes,
            aligned_checkins=sum(row.response_mode == "aligned" for row in checkins),
            unknown_checkins=sum(row.response_mode == "unknown" for row in checkins),
            deferred_checkins=sum(row.status == "deferred" for row in checkins),
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

    async def _checkins(
        self,
        user_id: int,
        usage_date: date,
        day_start: datetime,
        day_end: datetime,
    ) -> list[Checkin]:
        result = await self.session.execute(
            select(Checkin).where(
                Checkin.user_id == user_id,
                or_(
                    Checkin.usage_date == usage_date,
                    and_(
                        Checkin.usage_date.is_(None),
                        Checkin.window_start < day_end,
                        Checkin.window_end > day_start,
                    ),
                ),
            )
        )
        return list(result.scalars().all())

    async def _protected_blocks(
        self, user_id: int, day_start: datetime, day_end: datetime
    ) -> list[TimeBlock]:
        result = await self.session.execute(
            select(TimeBlock)
            .join(DailySchedule, TimeBlock.schedule_id == DailySchedule.id)
            .where(
                TimeBlock.user_id == user_id,
                TimeBlock.status != "cancelled",
                TimeBlock.start_at < day_end,
                TimeBlock.end_at > day_start,
                DailySchedule.user_id == user_id,
                DailySchedule.status == "confirmed",
                or_(
                    TimeBlock.flexibility == "protected",
                    TimeBlock.block_type.in_(("sleep", "prayer")),
                ),
            )
        )
        return list(result.scalars().all())

    async def _unknown_checkins(
        self, user_id: int, day_start: datetime, day_end: datetime
    ) -> list[Checkin]:
        result = await self.session.execute(
            select(Checkin).where(
                Checkin.user_id == user_id,
                Checkin.status == "answered",
                Checkin.response_mode == "unknown",
                Checkin.window_start < day_end,
                Checkin.window_end > day_start,
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
