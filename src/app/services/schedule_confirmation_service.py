from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailySchedule
from app.services.daily_control_service import (
    DailyControlValidationError,
    DailyScheduleService,
)


TERMINAL_REVIEW_STATUSES = frozenset(
    {"confirmed", "declined", "expired", "cancelled"}
)


class ScheduleConfirmationConflictError(DailyControlValidationError):
    pass


class ScheduleConfirmationService:
    """Owner-scoped, idempotent transitions for a schedule proposal draft."""

    def __init__(self, session: AsyncSession) -> None:
        self.schedules = DailyScheduleService(session)

    async def confirm(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
    ) -> DailySchedule:
        return await self._transition(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
            target="confirmed",
        )

    async def decline(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
    ) -> DailySchedule:
        return await self._transition(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
            target="declined",
        )

    async def expire(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
    ) -> DailySchedule:
        return await self._transition(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
            target="expired",
        )

    async def cancel(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
    ) -> DailySchedule:
        return await self._transition(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
            target="cancelled",
        )

    async def _transition(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
        target: str,
    ) -> DailySchedule:
        schedule = await self.schedules.get_by_id(
            schedule_id=schedule_id, user_id=user_id
        )
        if schedule.usage_date != usage_date:
            raise ScheduleConfirmationConflictError(
                "schedule proposal does not belong to the requested date"
            )
        if schedule.version != version:
            raise ScheduleConfirmationConflictError("schedule proposal version is stale")
        if schedule.status == target:
            return schedule
        if schedule.status != "draft":
            raise ScheduleConfirmationConflictError(
                f"cannot transition {schedule.status!r} proposal to {target!r}"
            )
        return await self.schedules.update_status(
            schedule_id=schedule.id, user_id=user_id, status=target
        )

