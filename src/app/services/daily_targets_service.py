from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import DailyTargetDefinition, DailyTargetProgress


VALID_UNITS: frozenset[str] = frozenset({"count", "ml", "liters", "minutes", "hours", "pages"})
VALID_MODES: frozenset[str] = frozenset({"minimum", "exact", "maximum"})


class DailyTargetError(Exception):
    pass


class DailyTargetValidationError(DailyTargetError):
    pass


class DailyTargetNotFoundError(DailyTargetError):
    pass


@dataclass(slots=True)
class TargetSummaryRow:
    definition: DailyTargetDefinition
    progress: DailyTargetProgress | None


class DailyTargetsService:
    """
    Service for daily quantitative targets (water, sleep, Quran pages, etc.).

    Unit normalization at write time:
        liters  → ml      (× 1000)
        hours   → minutes (× 60)
        count, ml, minutes, pages — stored as-is

    weekdays_mask bitmask: bit0=Mon(1) … bit6=Sun(64), 127 = every day.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Normalization ──────────────────────────────────────────────────────────

    @staticmethod
    def normalize(value: float, unit: str) -> tuple[float, str]:
        """Return (canonical_value, canonical_unit) for storage."""
        if unit == "liters":
            return value * 1000.0, "ml"
        if unit == "hours":
            return value * 60.0, "minutes"
        return value, unit

    # ── Validation ─────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_weekdays_mask(mask: int) -> None:
        if not (1 <= mask <= 127):
            raise DailyTargetValidationError(
                f"weekdays_mask must be 1..127, got {mask}"
            )

    @staticmethod
    def _validate_target_value(value: float) -> None:
        if value <= 0:
            raise DailyTargetValidationError(
                f"target_value must be > 0, got {value}"
            )

    @staticmethod
    def _validate_target_mode(mode: str) -> None:
        if mode not in VALID_MODES:
            raise DailyTargetValidationError(
                f"target_mode must be one of {sorted(VALID_MODES)}, got {mode!r}"
            )

    @staticmethod
    def _validate_actual_value(value: float) -> None:
        if value < 0:
            raise DailyTargetValidationError(
                f"actual_value must be >= 0, got {value}"
            )

    # ── Target definition ──────────────────────────────────────────────────────

    async def create_target_definition(
        self,
        *,
        title: str,
        unit: str,
        target_value: float,
        category: str = "general",
        target_mode: str = "minimum",
        priority: int = 100,
        weekdays_mask: int = 127,
        active: bool = True,
    ) -> DailyTargetDefinition:
        self._validate_weekdays_mask(weekdays_mask)
        self._validate_target_value(target_value)
        self._validate_target_mode(target_mode)

        canonical_value, canonical_unit = self.normalize(target_value, unit)

        now = now_tz()
        defn = DailyTargetDefinition(
            title=title,
            category=category,
            unit=canonical_unit,
            target_value=canonical_value,
            target_mode=target_mode,
            priority=priority,
            weekdays_mask=weekdays_mask,
            active=active,
            created_at=now,
            updated_at=now,
        )
        self.session.add(defn)
        await self.session.commit()
        await self.session.refresh(defn)
        return defn

    async def list_active_targets_for_date(
        self, target_date: date
    ) -> list[DailyTargetDefinition]:
        weekday_bit = 1 << target_date.weekday()
        stmt = (
            select(DailyTargetDefinition)
            .where(DailyTargetDefinition.active == True)  # noqa: E712
            .order_by(DailyTargetDefinition.priority.desc(), DailyTargetDefinition.id)
        )
        result = await self.session.execute(stmt)
        all_active = list(result.scalars().all())
        return [t for t in all_active if t.weekdays_mask & weekday_bit]

    # ── Progress ───────────────────────────────────────────────────────────────

    async def get_or_create_progress(
        self, target_id: int, usage_date: date
    ) -> DailyTargetProgress:
        existing = await self._fetch_progress(target_id, usage_date)
        if existing is not None:
            return existing

        defn = await self._get_definition(target_id)
        now = now_tz()
        progress = DailyTargetProgress(
            target_id=target_id,
            usage_date=usage_date,
            planned_value_snapshot=defn.target_value,
            actual_value=0.0,
            status="no_data",
            note=None,
            updated_at=now,
        )
        self.session.add(progress)
        await self.session.commit()
        await self.session.refresh(progress)
        return progress

    async def add_progress(
        self,
        target_id: int,
        usage_date: date,
        delta: float,
        note: str | None = None,
    ) -> DailyTargetProgress:
        self._validate_actual_value(delta)
        progress = await self.get_or_create_progress(target_id, usage_date)
        defn = await self._get_definition(target_id)
        return await self._apply_progress(
            progress, defn, progress.actual_value + delta, note
        )

    async def set_progress(
        self,
        target_id: int,
        usage_date: date,
        value: float,
        note: str | None = None,
    ) -> DailyTargetProgress:
        self._validate_actual_value(value)
        progress = await self.get_or_create_progress(target_id, usage_date)
        defn = await self._get_definition(target_id)
        return await self._apply_progress(progress, defn, value, note)

    async def get_summary_for_date(
        self, target_date: date
    ) -> list[TargetSummaryRow]:
        targets = await self.list_active_targets_for_date(target_date)
        rows: list[TargetSummaryRow] = []
        for target in targets:
            progress = await self._fetch_progress(target.id, target_date)
            rows.append(TargetSummaryRow(definition=target, progress=progress))
        return rows

    # ── Status ─────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_status(
        target_mode: str, actual_value: float, planned_value: float
    ) -> str:
        if target_mode == "minimum":
            if actual_value >= planned_value:
                return "reached"
            if actual_value > 0:
                return "partial"
            return "in_progress"
        if target_mode == "exact":
            if actual_value == planned_value:
                return "reached"
            if actual_value > planned_value:
                return "exceeded"
            return "in_progress"
        if target_mode == "maximum":
            if actual_value > planned_value:
                return "exceeded"
            return "in_progress"
        return "in_progress"

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _fetch_progress(
        self, target_id: int, usage_date: date
    ) -> DailyTargetProgress | None:
        stmt = select(DailyTargetProgress).where(
            DailyTargetProgress.target_id == target_id,
            DailyTargetProgress.usage_date == usage_date,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_definition(self, target_id: int) -> DailyTargetDefinition:
        stmt = select(DailyTargetDefinition).where(
            DailyTargetDefinition.id == target_id
        )
        result = await self.session.execute(stmt)
        defn = result.scalar_one_or_none()
        if defn is None:
            raise DailyTargetNotFoundError(
                f"DailyTargetDefinition id={target_id} not found"
            )
        return defn

    async def _apply_progress(
        self,
        progress: DailyTargetProgress,
        defn: DailyTargetDefinition,
        new_value: float,
        note: str | None,
    ) -> DailyTargetProgress:
        progress.actual_value = new_value
        progress.status = self.compute_status(
            defn.target_mode, new_value, progress.planned_value_snapshot
        )
        progress.updated_at = now_tz()
        if note is not None:
            progress.note = note
        await self.session.commit()
        await self.session.refresh(progress)
        return progress
