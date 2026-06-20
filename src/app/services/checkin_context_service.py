from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db.models import Checkin


class CheckinContextService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, *, user_id: int) -> Checkin | None:
        result = await self.session.execute(
            select(Checkin)
            .where(
                Checkin.user_id == user_id,
                Checkin.status.in_(("pending", "sent", "open")),
            )
            .order_by(Checkin.prompted_at.desc(), Checkin.id.desc())
        )
        cutoff = now_tz() - timedelta(hours=4)
        now = now_tz()
        for row in result.scalars().all():
            prompted = row.prompted_at
            if prompted.tzinfo is None:
                prompted = prompted.replace(tzinfo=APP_TZ)
            if cutoff <= prompted <= now:
                return row
        return None

