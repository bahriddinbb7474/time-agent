from __future__ import annotations

from datetime import date, datetime, timedelta

from apscheduler.triggers.date import DateTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.services.checkin_policy_service import CheckinPolicyService


async def deliver_pending_checkin(session, *, checkin_id: int, bot, user_id: int) -> bool:
    from sqlalchemy import select
    from app.db.models import Checkin, TimeBlock

    row = await session.get(Checkin, checkin_id)
    if row is None or row.user_id != user_id or row.status != "pending":
        return False
    block_result = await session.execute(
        select(TimeBlock).where(
            TimeBlock.schedule_id == row.schedule_id,
            TimeBlock.start_at < row.window_end,
            TimeBlock.end_at > row.window_start,
            TimeBlock.status != "cancelled",
        ).order_by(TimeBlock.start_at, TimeBlock.id)
    )
    block = block_result.scalars().first()
    lines = [
        "Что было за этот интервал?",
        "Ответьте текстом или голосом.",
        "",
        "Примеры:",
        "• не помню",
        "• работал с оплатами",
        "• занимался Time-Agent",
        "• отдыхал",
        "• потерял время впустую",
    ]
    if block is not None:
        lines.extend(("", f"По плану было: {block.title}"))
    start = row.window_start.strftime("%H:%M")
    end = row.window_end.strftime("%H:%M")
    lines.append(f"Интервал: [{start}-{end}]({start}-{end})")
    await bot.send_message(user_id, "\n".join(lines))
    row.status = "sent"
    row.prompted_at = datetime.now(APP_TZ)
    row.updated_at = row.prompted_at
    await session.commit()
    return True


async def run_checkin_job(checkin_id: int, bot, user_id: int) -> None:
    from app.db.database import get_sessionmaker

    async with get_sessionmaker()() as session:
        await deliver_pending_checkin(
            session,
            checkin_id=checkin_id,
            bot=bot,
            user_id=user_id,
        )


class CheckinSchedulerService:
    def __init__(self, session: AsyncSession) -> None:
        self.policy = CheckinPolicyService(session)

    async def recover(
        self,
        *,
        scheduler,
        user_id: int,
        today: date,
        interval_minutes: int = 120,
        now: datetime | None = None,
        bot=None,
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
                    kwargs={"checkin_id": row.id, "bot": bot, "user_id": user_id},
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
