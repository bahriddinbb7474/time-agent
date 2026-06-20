from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import Checkin
from app.services.daily_control_service import (
    ActivityEntryService,
    DailyControlNotFoundError,
    DailyControlValidationError,
)
from app.services.checkin_response_classifier import CheckinResponseClassifier
from app.services.categories import normalize_activity_time_group


class CheckinResponseService:
    ACTIONS = {
        "aligned": ("answered", "aligned"),
        "started": ("answered", "started"),
        "defer": ("deferred", "deferred"),
        # Owner explicitly reported no recollection. This is check-in state only:
        # it must not create an ActivityEntry or imply waste.
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

    async def record_confirmed_activity(
        self,
        *,
        checkin_id: int,
        user_id: int,
        title: str,
        category: str,
        source: str = "voice_llm",
        response_mode: str = "voice_activity",
        waste_explicit: bool = False,
    ) -> Checkin:
        value = " ".join((title or "").split())
        category = normalize_activity_time_group(category)
        if not value or len(value) > 256:
            raise DailyControlValidationError(
                "confirmed activity must contain 1 to 256 characters"
            )
        if category == "waste" and not waste_explicit:
            raise DailyControlValidationError(
                "waste requires explicit owner statement and confirmation"
            )
        result = await self.session.execute(
            select(Checkin).where(Checkin.id == checkin_id, Checkin.user_id == user_id)
        )
        checkin = result.scalar_one_or_none()
        if checkin is None:
            raise DailyControlNotFoundError(f"Checkin id={checkin_id} not found")
        if checkin.status == "answered" and checkin.response_mode == response_mode:
            return checkin
        if checkin.status not in {"sent", "open"}:
            raise DailyControlValidationError("check-in cannot accept activity")
        await ActivityEntryService(self.session).create(
            user_id=user_id,
            start_at=checkin.window_start.replace(tzinfo=now_tz().tzinfo),
            end_at=checkin.window_end.replace(tzinfo=now_tz().tzinfo),
            title=value,
            category=category,
            source=source,
            owner_confirmed=True,
            waste_marked_by_owner=category == "waste" and waste_explicit,
        )
        checkin.status = "answered"
        checkin.response_mode = response_mode
        checkin.answered_at = now_tz()
        checkin.updated_at = checkin.answered_at
        await self.session.commit()
        await self.session.refresh(checkin)
        return checkin

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
