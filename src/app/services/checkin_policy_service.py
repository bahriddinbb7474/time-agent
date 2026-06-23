from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db.models import ActivityEntry, Checkin, DailySchedule, TimeBlock
from app.services.daily_control_service import CheckinService, DailyControlValidationError


PROTECTED_CHECKIN_TYPES = frozenset({"sleep", "prayer", "protected"})
MIN_CHECKIN_GAP = timedelta(minutes=30)


class CheckinPolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.checkins = CheckinService(session)

    async def plan_for_date(
        self,
        *,
        user_id: int,
        usage_date: date,
        interval_minutes: int = 120,
    ) -> list[Checkin]:
        if interval_minutes not in {60, 120}:
            raise DailyControlValidationError("check-in interval must be 60 or 120 minutes")
        schedule = await self._confirmed_schedule(user_id, usage_date)
        if schedule is None:
            return []
        day_start = datetime.combine(usage_date, time.min, APP_TZ)
        day_end = day_start + timedelta(days=1)
        covered = await self._covered_intervals(
            schedule_id=schedule.id,
            user_id=user_id,
            day_start=day_start,
            day_end=day_end,
        )
        interval = timedelta(minutes=interval_minutes)
        windows: list[tuple[datetime, datetime]] = []
        for gap_start, gap_end in self._subtract(day_start, day_end, covered):
            if gap_end - gap_start < MIN_CHECKIN_GAP:
                continue
            cursor = gap_start
            while cursor < gap_end:
                remaining = gap_end - cursor
                window_end = (
                    gap_end
                    if remaining <= interval + MIN_CHECKIN_GAP
                    else cursor + interval
                )
                windows.append((cursor, window_end))
                cursor = window_end
        await self._expire_stale_pending(
            schedule_id=schedule.id,
            user_id=user_id,
            windows=windows,
        )
        result: list[Checkin] = []
        for window_start, window_end in windows:
            result.append(
                await self.checkins.create(
                    user_id=user_id,
                    schedule_id=schedule.id,
                    schedule_version=schedule.version,
                    usage_date=usage_date,
                    window_start=window_start,
                    window_end=window_end,
                    prompted_at=window_end,
                )
            )
        return result

    async def _confirmed_schedule(
        self, user_id: int, usage_date: date
    ) -> DailySchedule | None:
        result = await self.session.execute(
            select(DailySchedule).where(
                DailySchedule.user_id == user_id,
                DailySchedule.usage_date == usage_date,
                DailySchedule.status == "confirmed",
            )
        )
        return result.scalar_one_or_none()

    async def _covered_intervals(
        self,
        *,
        schedule_id: int,
        user_id: int,
        day_start: datetime,
        day_end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        protected_result = await self.session.execute(
            select(TimeBlock).where(
                TimeBlock.schedule_id == schedule_id,
                TimeBlock.user_id == user_id,
                (
                    TimeBlock.block_type.in_(PROTECTED_CHECKIN_TYPES)
                    | (TimeBlock.flexibility == "protected")
                ),
                TimeBlock.status != "cancelled",
            )
        )
        activity_result = await self.session.execute(
            select(ActivityEntry).where(
                ActivityEntry.user_id == user_id,
                ActivityEntry.owner_confirmed.is_(True),
                ActivityEntry.start_at < day_end,
                ActivityEntry.end_at > day_start,
            )
        )
        unknown_result = await self.session.execute(
            select(Checkin).where(
                Checkin.user_id == user_id,
                Checkin.status == "answered",
                Checkin.response_mode.in_({"unknown", "no_data"}),
                Checkin.window_start < day_end,
                Checkin.window_end > day_start,
            )
        )
        rows = (
            list(protected_result.scalars().all())
            + list(activity_result.scalars().all())
            + list(unknown_result.scalars().all())
        )
        intervals = sorted(
            (
                max(day_start, self._aware(row.start_at if isinstance(row, (TimeBlock, ActivityEntry)) else row.window_start)),
                min(day_end, self._aware(row.end_at if isinstance(row, (TimeBlock, ActivityEntry)) else row.window_end)),
            )
            for row in rows
        )
        merged: list[tuple[datetime, datetime]] = []
        for start, end in intervals:
            if start >= end:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    async def _expire_stale_pending(
        self,
        *,
        schedule_id: int,
        user_id: int,
        windows: list[tuple[datetime, datetime]],
    ) -> None:
        result = await self.session.execute(
            select(Checkin).where(
                Checkin.schedule_id == schedule_id,
                Checkin.user_id == user_id,
                Checkin.status == "pending",
            )
        )
        expected = {(start, end) for start, end in windows}
        changed = False
        for row in result.scalars().all():
            window = (self._aware(row.window_start), self._aware(row.window_end))
            if window not in expected:
                row.status = "expired"
                row.updated_at = now_tz()
                changed = True
        if changed:
            await self.session.commit()

    @staticmethod
    def _subtract(
        day_start: datetime,
        day_end: datetime,
        covered: list[tuple[datetime, datetime]],
    ) -> list[tuple[datetime, datetime]]:
        gaps: list[tuple[datetime, datetime]] = []
        cursor = day_start
        for start, end in covered:
            if cursor < start:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < day_end:
            gaps.append((cursor, day_end))
        return gaps

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=APP_TZ)
        return value.astimezone(APP_TZ)
