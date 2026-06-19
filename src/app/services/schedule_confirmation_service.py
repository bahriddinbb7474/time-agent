from __future__ import annotations

from datetime import date

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import DailySchedule, TimeBlock
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
        self.session = session
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

    async def rebuild(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
    ) -> DailySchedule:
        schedule = await self._owned_version(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
        )
        if schedule.status == "confirmed":
            raise ScheduleConfirmationConflictError(
                "confirmed schedule cannot be replaced by rebuild"
            )
        if schedule.status == "archived":
            raise ScheduleConfirmationConflictError("archived schedule cannot be rebuilt")
        await self.session.execute(
            delete(TimeBlock).where(
                TimeBlock.schedule_id == schedule.id,
                TimeBlock.user_id == user_id,
            )
        )
        schedule.status = "draft"
        schedule.version += 1
        schedule.confirmed_at = None
        schedule.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def _transition(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
        target: str,
    ) -> DailySchedule:
        schedule = await self._owned_version(
            schedule_id=schedule_id,
            user_id=user_id,
            usage_date=usage_date,
            version=version,
        )
        if schedule.status == target:
            return schedule
        if schedule.status != "draft":
            raise ScheduleConfirmationConflictError(
                f"cannot transition {schedule.status!r} proposal to {target!r}"
            )
        return await self.schedules.update_status(
            schedule_id=schedule.id, user_id=user_id, status=target
        )

    async def _owned_version(
        self,
        *,
        schedule_id: int,
        user_id: int,
        usage_date: date,
        version: int,
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
        return schedule
