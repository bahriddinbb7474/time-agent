from __future__ import annotations

from datetime import date, datetime, timedelta

from apscheduler.triggers.date import DateTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.services.checkin_policy_service import CheckinPolicyService


async def run_checkin_job(checkin_id: int) -> None:
    """Stage 20.4-B contract; Telegram delivery is connected in 20.4-C."""
    del checkin_id


class CheckinSchedulerService:
    def __init__(self, session: AsyncSession) -> None:
        self.policy = CheckinPolicyService(session)

    async def recover(
        self,
        *,
        scheduler,
        user_id: int,
        today: date,
        interval_minutes: int = 60,
        now: datetime | None = None,
    ) -> list[int]:
        current = now or datetime.now(APP_TZ)
        planned_ids: list[int] = []
        for usage_date in (today, today + timedelta(days=1)):
            rows = await self.policy.plan_for_date(
                user_id=user_id,
                usage_date=usage_date,
                interval_minutes=interval_minutes,
            )
            for row in rows:
                run_at = self._aware(row.prompted_at)
                if row.status != "pending" or run_at < current:
                    continue
                scheduler.add_job(
                    run_checkin_job,
                    trigger=DateTrigger(run_date=run_at, timezone=APP_TZ),
                    id=f"checkin_{row.id}",
                    kwargs={"checkin_id": row.id},
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=300,
                )
                planned_ids.append(row.id)
        return planned_ids

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=APP_TZ)
        return value.astimezone(APP_TZ)

