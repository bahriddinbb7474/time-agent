from __future__ import annotations

from datetime import datetime, timedelta
import secrets

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import OAuthState


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=APP_TZ)
    return dt


class OAuthStateRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_state(
        self,
        user_id: int,
        code_verifier: str,
        ttl_minutes: int = 10,
    ) -> str:
        now = datetime.now(APP_TZ)
        expires = now + timedelta(minutes=ttl_minutes)

        state = secrets.token_urlsafe(32)

        obj = OAuthState(
            user_id=user_id,
            state=state,
            code_verifier=code_verifier,
            created_at=now,
            expires_at=expires,
            is_used=False,
        )
        self.session.add(obj)
        await self.session.commit()
        return state

    async def consume_state_by_state(self, state: str) -> tuple[int, str] | None:
        now = datetime.now(APP_TZ)

        res = await self.session.execute(
            select(OAuthState).where(OAuthState.state == state)
        )
        row = res.scalar_one_or_none()
        if row is None:
            return None
        if row.is_used:
            return None

        expires_at = _ensure_aware(row.expires_at)
        if expires_at <= now:
            return None

        await self.session.execute(
            update(OAuthState)
            .where(OAuthState.id == row.id, OAuthState.is_used.is_(False))
            .values(is_used=True)
        )
        await self.session.commit()
        return int(row.user_id), str(row.code_verifier)

    async def consume_state(self, user_id: int, state: str) -> bool:
        now = datetime.now(APP_TZ)

        q = select(OAuthState).where(
            OAuthState.user_id == user_id,
            OAuthState.state == state,
        )
        res = await self.session.execute(q)
        row = res.scalar_one_or_none()

        if row is None:
            return False
        if row.is_used:
            return False

        expires_at = _ensure_aware(row.expires_at)
        if expires_at <= now:
            return False

        await self.session.execute(
            update(OAuthState)
            .where(OAuthState.id == row.id, OAuthState.is_used.is_(False))
            .values(is_used=True)
        )
        await self.session.commit()
        return True
