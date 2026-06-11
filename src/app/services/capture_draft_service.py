from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CaptureDraftRecord
from app.services.capture_router_service import CaptureDraft


CAPTURE_DRAFT_STATUS_PENDING = "pending"
CAPTURE_DRAFT_STATUS_CONFIRMED = "confirmed"
CAPTURE_DRAFT_STATUS_EXPIRED = "expired"
CAPTURE_DRAFT_STATUS_CANCELLED = "cancelled"

CAPTURE_DRAFT_SOURCE_TEXT = "text"
CAPTURE_DRAFT_TTL = timedelta(hours=48)


class CaptureDraftService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_pending_draft(
        self,
        *,
        chat_id: int,
        user_id: int,
        draft: CaptureDraft,
        source: str = CAPTURE_DRAFT_SOURCE_TEXT,
        transcript: str | None = None,
        now: datetime | None = None,
    ) -> CaptureDraftRecord:
        created_at = now or _utc_now()
        record = CaptureDraftRecord(
            telegram_chat_id=chat_id,
            telegram_user_id=user_id,
            source=source,
            raw_text=draft.text,
            transcript=transcript,
            suggested_type=draft.kind,
            created_at=created_at,
            expires_at=created_at + CAPTURE_DRAFT_TTL,
            status=CAPTURE_DRAFT_STATUS_PENDING,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_latest_pending_draft(
        self,
        *,
        chat_id: int,
        user_id: int,
    ) -> CaptureDraftRecord | None:
        return await self._get_latest_by_status(
            chat_id=chat_id,
            user_id=user_id,
            status=CAPTURE_DRAFT_STATUS_PENDING,
        )

    async def get_latest_expired_draft(
        self,
        *,
        chat_id: int,
        user_id: int,
    ) -> CaptureDraftRecord | None:
        return await self._get_latest_by_status(
            chat_id=chat_id,
            user_id=user_id,
            status=CAPTURE_DRAFT_STATUS_EXPIRED,
        )

    async def expire_old_pending_drafts(
        self,
        *,
        chat_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> int:
        result = await self.session.execute(
            update(CaptureDraftRecord)
            .where(CaptureDraftRecord.telegram_chat_id == chat_id)
            .where(CaptureDraftRecord.telegram_user_id == user_id)
            .where(CaptureDraftRecord.status == CAPTURE_DRAFT_STATUS_PENDING)
            .where(CaptureDraftRecord.expires_at <= (now or _utc_now()))
            .values(status=CAPTURE_DRAFT_STATUS_EXPIRED)
        )
        await self.session.commit()
        return result.rowcount or 0

    async def mark_confirmed(self, record: CaptureDraftRecord) -> None:
        await self._mark_status(record, CAPTURE_DRAFT_STATUS_CONFIRMED)

    async def mark_cancelled(self, record: CaptureDraftRecord) -> None:
        await self._mark_status(record, CAPTURE_DRAFT_STATUS_CANCELLED)

    def to_capture_draft(self, record: CaptureDraftRecord) -> CaptureDraft:
        return CaptureDraft(
            kind=record.suggested_type,
            text=record.raw_text,
            title=record.raw_text,
        )

    async def _get_latest_by_status(
        self,
        *,
        chat_id: int,
        user_id: int,
        status: str,
    ) -> CaptureDraftRecord | None:
        result = await self.session.execute(
            select(CaptureDraftRecord)
            .where(CaptureDraftRecord.telegram_chat_id == chat_id)
            .where(CaptureDraftRecord.telegram_user_id == user_id)
            .where(CaptureDraftRecord.status == status)
            .order_by(CaptureDraftRecord.created_at.desc(), CaptureDraftRecord.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _mark_status(self, record: CaptureDraftRecord, status: str) -> None:
        record.status = status
        await self.session.commit()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
