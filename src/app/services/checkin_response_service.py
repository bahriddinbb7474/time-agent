from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import Checkin
from app.services.daily_control_service import DailyControlNotFoundError
from app.services.checkin_response_classifier import CheckinResponseClassifier


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
        self.classifier = CheckinResponseClassifier()

    async def respond_value(
        self, *, checkin_id: int, user_id: int, value: str
    ) -> Checkin:
        intent = self.classifier.classify(value).intent
        if intent == "cancel":
            return await self._apply(
                checkin_id=checkin_id, user_id=user_id,
                status="skipped", response_mode="cancel",
            )
        if intent in {"unsupported", "other_text"}:
            if intent == "unsupported":
                raise ValueError("unsupported check-in response")
            intent = "other"
        return await self.respond(checkin_id=checkin_id, user_id=user_id, action=intent)

    async def respond(self, *, checkin_id: int, user_id: int, action: str) -> Checkin:
        if action not in self.ACTIONS:
            raise ValueError("unsupported check-in action")
        status, mode = self.ACTIONS[action]
        return await self._apply(
            checkin_id=checkin_id, user_id=user_id, status=status, response_mode=mode
        )

    async def _apply(
        self, *, checkin_id: int, user_id: int, status: str, response_mode: str
    ) -> Checkin:
        result = await self.session.execute(
            select(Checkin).where(Checkin.id == checkin_id, Checkin.user_id == user_id)
        )
        checkin = result.scalar_one_or_none()
        if checkin is None:
            raise DailyControlNotFoundError(f"Checkin id={checkin_id} not found")
        if checkin.status in {"answered", "deferred", "skipped", "expired"}:
            return checkin
        checkin.status = status
        checkin.response_mode = response_mode
        checkin.answered_at = now_tz() if status == "answered" else None
        checkin.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(checkin)
        return checkin
