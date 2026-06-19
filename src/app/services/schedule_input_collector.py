from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, UserRoutine
from app.services.prayer_times_service import PrayerTimesService


@dataclass(frozen=True, slots=True)
class CollectedBlock:
    start_at: datetime
    end_at: datetime
    title: str
    category: str
    block_type: str
    flexibility: str
    source_type: str
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class CollectionIssue:
    title: str
    source_type: str
    source_id: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class CollectedScheduleInputs:
    blocks: tuple[CollectedBlock, ...]
    issues: tuple[CollectionIssue, ...]


class ScheduleInputCollector:
    """Read existing project inputs without mutating their source tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def collect(
        self, *, usage_date: date, user_id: int, timezone: ZoneInfo
    ) -> CollectedScheduleInputs:
        del user_id  # The current application is owner-only; Task has no owner column.
        blocks: list[CollectedBlock] = []
        issues: list[CollectionIssue] = []
        prayer_times = await PrayerTimesService(self.session).get_cached_prayer_times(
            usage_date
        )
        if prayer_times is not None:
            blocks.extend(self._prayer_blocks(usage_date, timezone, prayer_times))
            blocks.extend(await self._sleep_blocks(usage_date, timezone, prayer_times.fajr))
        task_result = await self.session.execute(
            select(Task)
            .where(Task.status.in_(("todo", "later")), Task.planned_at.is_not(None))
            .order_by(Task.planned_at, Task.id)
        )
        for task in task_result.scalars().all():
            planned_at = self._local_datetime(task.planned_at, timezone)
            if planned_at.date() != usage_date:
                continue
            if task.duration_min is None or task.duration_min <= 0:
                issues.append(
                    CollectionIssue(
                        title=task.title,
                        source_type="task",
                        source_id=task.id,
                        reason="task has no positive duration",
                    )
                )
                continue
            end_at = planned_at + timedelta(minutes=task.duration_min)
            if end_at > datetime.combine(
                usage_date + timedelta(days=1), time.max, timezone
            ):
                issues.append(
                    CollectionIssue(
                        title=task.title,
                        source_type="task",
                        source_id=task.id,
                        reason="task extends beyond the next local day",
                    )
                )
                continue
            blocks.append(
                CollectedBlock(
                    start_at=planned_at,
                    end_at=end_at,
                    title=task.title,
                    category=task.category,
                    block_type="fixed_task",
                    flexibility="fixed",
                    source_type="task",
                    source_id=task.id,
                )
            )
        return CollectedScheduleInputs(tuple(blocks), tuple(issues))

    @staticmethod
    def _prayer_blocks(usage_date, timezone, prayer_times) -> list[CollectedBlock]:
        result: list[CollectedBlock] = []
        day_start = datetime.combine(usage_date, time.min, timezone)
        for name, value in (
            ("Fajr", prayer_times.fajr),
            ("Dhuhr", prayer_times.dhuhr),
            ("Asr", prayer_times.asr),
            ("Maghrib", prayer_times.maghrib),
            ("Isha", prayer_times.isha),
        ):
            prayer_at = datetime.combine(usage_date, value, timezone)
            result.append(
                CollectedBlock(
                    start_at=max(day_start, prayer_at - timedelta(minutes=15)),
                    end_at=prayer_at + timedelta(minutes=20),
                    title=name,
                    category="prayer",
                    block_type="prayer",
                    flexibility="protected",
                    source_type="prayer_cache",
                )
            )
        return result

    async def _sleep_blocks(
        self, usage_date: date, timezone: ZoneInfo, fajr: time
    ) -> list[CollectedBlock]:
        mode = "summer" if (fajr.hour, fajr.minute) < (5, 30) else "winter"
        result = await self.session.execute(
            select(UserRoutine).where(UserRoutine.mode == mode)
        )
        routine = result.scalar_one_or_none()
        if routine is None:
            return []
        blocks = self._routine_interval(
            usage_date,
            timezone,
            routine.sleep_start,
            routine.sleep_end,
            title="Sleep",
            source_id=routine.id,
        )
        if routine.second_sleep_start is not None and routine.second_sleep_end is not None:
            blocks.extend(
                self._routine_interval(
                    usage_date,
                    timezone,
                    routine.second_sleep_start,
                    routine.second_sleep_end,
                    title="Second sleep",
                    source_id=routine.id,
                )
            )
        return blocks

    @staticmethod
    def _routine_interval(
        usage_date: date,
        timezone: ZoneInfo,
        start: time,
        end: time,
        *,
        title: str,
        source_id: int,
    ) -> list[CollectedBlock]:
        day_start = datetime.combine(usage_date, time.min, timezone)
        local_start = datetime.combine(usage_date, start, timezone)
        local_end = datetime.combine(usage_date, end, timezone)
        intervals: list[tuple[datetime, datetime]]
        if (start.hour, start.minute) < (end.hour, end.minute):
            intervals = [(local_start, local_end)]
        else:
            intervals = []
            if local_end > day_start:
                intervals.append((day_start, local_end))
            intervals.append((local_start, local_end + timedelta(days=1)))
        return [
            CollectedBlock(
                start_at=start_at,
                end_at=end_at,
                title=title,
                category="sleep",
                block_type="sleep",
                flexibility="protected",
                source_type="routine",
                source_id=source_id,
            )
            for start_at, end_at in intervals
            if end_at > start_at
        ]

    @staticmethod
    def _local_datetime(value: datetime, timezone: ZoneInfo) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)

