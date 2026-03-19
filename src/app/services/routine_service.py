from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import UserRoutine
from app.services.prayer_times_service import PrayerTimesService


class RoutineService:
    def __init__(
        self,
        session: AsyncSession,
        prayer_times_service: PrayerTimesService,
    ) -> None:
        self.session = session
        self.prayer_times_service = prayer_times_service

    async def get_current_mode(self, target_date: date | None = None) -> str:
        """
        summer mode:
            if fajr < 05:30

        winter mode:
            otherwise
        """
        if target_date is None:
            target_date = datetime.now(APP_TZ).date()

        prayer_times = await self.prayer_times_service.get_prayer_times(target_date)

        if prayer_times.fajr < time(hour=5, minute=30, tzinfo=APP_TZ):
            return "summer"

        return "winter"

    async def is_sleep_time(self, dt: datetime) -> bool:
        """
        Checks primary sleep interval for the current mode.

        Supports overnight intervals, e.g. 23:00 -> 05:00.
        """
        routine = await self._get_routine_for_datetime(dt)

        if routine is None:
            return False

        return self._time_in_interval(
            target=dt.timetz(),
            start=routine.sleep_start,
            end=routine.sleep_end,
        )

    async def is_second_sleep(self, dt: datetime) -> bool:
        """
        Checks secondary sleep interval for the current mode.

        For winter mode it usually returns False because
        second_sleep_start / second_sleep_end are NULL.
        """
        routine = await self._get_routine_for_datetime(dt)

        if routine is None:
            return False

        if routine.second_sleep_start is None or routine.second_sleep_end is None:
            return False

        return self._time_in_interval(
            target=dt.timetz(),
            start=routine.second_sleep_start,
            end=routine.second_sleep_end,
        )

    async def _get_routine_for_datetime(self, dt: datetime) -> UserRoutine | None:
        local_dt = self._ensure_app_tz(dt)
        mode = await self.get_current_mode(local_dt.date())
        return await self._get_routine_by_mode(mode)

    async def _get_routine_by_mode(self, mode: str) -> UserRoutine | None:
        stmt = select(UserRoutine).where(UserRoutine.mode == mode)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _ensure_app_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)

    @staticmethod
    def _time_in_interval(target: time, start: time, end: time) -> bool:
        """
        Handles both normal and overnight intervals.

        Examples:
            01:00 in 23:00->05:00 => True
            12:00 in 09:00->18:00 => True
        """
        target_hm = (target.hour, target.minute)
        start_hm = (start.hour, start.minute)
        end_hm = (end.hour, end.minute)

        if start_hm <= end_hm:
            return start_hm <= target_hm < end_hm

        return target_hm >= start_hm or target_hm < end_hm
