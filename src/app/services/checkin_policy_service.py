from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import Checkin, DailySchedule, TimeBlock
from app.services.daily_control_service import CheckinService, DailyControlValidationError


PROTECTED_CHECKIN_TYPES = frozenset({"sleep", "prayer"})


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
        protected = await self._protected_blocks(schedule.id, user_id)
        result: list[Checkin] = []
        cursor = datetime.combine(usage_date, time.min, APP_TZ)
        day_end = cursor + timedelta(days=1)
        interval = timedelta(minutes=interval_minutes)
        while cursor < day_end:
            window_end = min(cursor + interval, day_end)
            suppressed = any(
                block.start_at.replace(tzinfo=APP_TZ) < window_end
                and block.end_at.replace(tzinfo=APP_TZ) > cursor
                for block in protected
            )
            result.append(
                await self.checkins.create(
                    user_id=user_id,
                    schedule_id=schedule.id,
                    schedule_version=schedule.version,
                    usage_date=usage_date,
                    window_start=cursor,
                    window_end=window_end,
                    prompted_at=window_end,
                    status="deferred" if suppressed else "pending",
                    response_mode="protected_slot" if suppressed else None,
                )
            )
            cursor = window_end
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

    async def _protected_blocks(self, schedule_id: int, user_id: int) -> list[TimeBlock]:
        result = await self.session.execute(
            select(TimeBlock).where(
                TimeBlock.schedule_id == schedule_id,
                TimeBlock.user_id == user_id,
                TimeBlock.block_type.in_(PROTECTED_CHECKIN_TYPES),
                TimeBlock.status != "cancelled",
            )
        )
        return list(result.scalars().all())
