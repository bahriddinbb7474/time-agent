from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import Checkin
from app.services.daily_control_service import DailyControlNotFoundError


class CheckinResponseService:
    ACTIONS = {
        "aligned": ("answered", "aligned"),
        "started": ("answered", "started"),
        "defer": ("deferred", "deferred"),
        "unknown": ("answered", "unknown"),
        "other": ("open", "other"),
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def respond(self, *, checkin_id: int, user_id: int, action: str) -> Checkin:
        result = await self.session.execute(
            select(Checkin).where(Checkin.id == checkin_id, Checkin.user_id == user_id)
        )
        checkin = result.scalar_one_or_none()
        if checkin is None:
            raise DailyControlNotFoundError(f"Checkin id={checkin_id} not found")
        if checkin.status in {"answered", "deferred", "skipped", "expired"}:
            return checkin
        if action not in self.ACTIONS:
            raise ValueError("unsupported check-in action")
        status, mode = self.ACTIONS[action]
        checkin.status = status
        checkin.response_mode = mode
        checkin.answered_at = now_tz() if status == "answered" else None
        checkin.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(checkin)
        return checkin

