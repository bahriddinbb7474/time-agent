from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import DailyHealthContext


@dataclass(slots=True)
class DailyContextPolicy:
    date: date
    is_siyam_day: bool
    hydration_daylight_suppressed: bool
    low_energy_mode: bool
    siyam_state_source: str


class DailyContextService:
    """Read-mostly daily context foundation for siyam-first health policy."""

    SIYAM_SOURCE_HEURISTIC = "heuristic"
    SIYAM_SOURCE_EXPLICIT = "explicit"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_explicit_siyam_for_today(
        self,
        *,
        is_siyam_day: bool,
    ) -> DailyContextPolicy:
        today = now_tz().date()
        return await self.set_explicit_siyam_for_date(
            target_date=today,
            is_siyam_day=is_siyam_day,
        )

    async def set_explicit_siyam_for_date(
        self,
        *,
        target_date: date,
        is_siyam_day: bool,
    ) -> DailyContextPolicy:
        now = now_tz()
        existing = await self._get_row_by_date(target_date)

        if existing is None:
            row = DailyHealthContext(
                date=target_date,
                is_siyam_day=is_siyam_day,
                siyam_state_source=self.SIYAM_SOURCE_EXPLICIT,
                hydration_daylight_suppressed=is_siyam_day,
                low_energy_mode=False,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
            await self.session.commit()
            await self.session.refresh(row)
            return self._to_policy(row)

        # Idempotent explicit override: if target state is already stored as explicit,
        # skip write path to preserve updated_at and avoid extra commit.
        if (
            existing.siyam_state_source == self.SIYAM_SOURCE_EXPLICIT
            and existing.is_siyam_day == is_siyam_day
            and existing.hydration_daylight_suppressed == is_siyam_day
        ):
            return self._to_policy(existing)

        existing.is_siyam_day = is_siyam_day
        existing.siyam_state_source = self.SIYAM_SOURCE_EXPLICIT
        existing.hydration_daylight_suppressed = is_siyam_day
        existing.updated_at = now

        await self.session.commit()
        await self.session.refresh(existing)
        return self._to_policy(existing)

    async def get_or_create_policy_for_date(self, target_date: date) -> DailyContextPolicy:
        existing = await self._get_row_by_date(target_date)
        if existing is None:
            existing = await self._create_default_row(target_date)

        return self._to_policy(existing)

    async def get_policy_for_date(self, target_date: date) -> DailyContextPolicy | None:
        existing = await self._get_row_by_date(target_date)
        if existing is not None and self._is_explicit(existing):
            return self._to_policy(existing)

        default_is_siyam = self._detect_default_siyam_day(target_date)
        return DailyContextPolicy(
            date=target_date,
            is_siyam_day=default_is_siyam,
            hydration_daylight_suppressed=default_is_siyam,
            low_energy_mode=False,
            siyam_state_source=self.SIYAM_SOURCE_HEURISTIC,
        )

    async def _get_row_by_date(self, target_date: date) -> DailyHealthContext | None:
        stmt = select(DailyHealthContext).where(DailyHealthContext.date == target_date)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_default_row(self, target_date: date) -> DailyHealthContext:
        is_siyam_day = self._detect_default_siyam_day(target_date)
        now = now_tz()

        row = DailyHealthContext(
            date=target_date,
            is_siyam_day=is_siyam_day,
            siyam_state_source=self.SIYAM_SOURCE_HEURISTIC,
            hydration_daylight_suppressed=is_siyam_day,
            low_energy_mode=False,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    @staticmethod
    def _detect_default_siyam_day(target_date: date) -> bool:
        # Existing fallback heuristic: Monday / Thursday
        return target_date.weekday() in (0, 3)

    @staticmethod
    def _to_policy(row: DailyHealthContext) -> DailyContextPolicy:
        return DailyContextPolicy(
            date=row.date,
            is_siyam_day=row.is_siyam_day,
            hydration_daylight_suppressed=row.hydration_daylight_suppressed,
            low_energy_mode=row.low_energy_mode,
            siyam_state_source=row.siyam_state_source,
        )

    @classmethod
    def _is_explicit(cls, row: DailyHealthContext) -> bool:
        return row.siyam_state_source == cls.SIYAM_SOURCE_EXPLICIT

