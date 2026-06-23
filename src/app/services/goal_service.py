from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import Goal
from app.services.categories import TIME_GROUP_CODES


VALID_GOAL_HORIZONS = frozenset({"daily", "monthly", "six_month", "yearly"})
VALID_GOAL_STATUSES = frozenset({"active", "paused", "done", "archived"})
VALID_GOAL_UNITS = frozenset({"count", "ml", "minutes", "hours", "pages"})
VALID_GOAL_TARGET_MODES = frozenset({"minimum", "exact", "maximum"})
FORBIDDEN_GOAL_TIME_GROUPS = frozenset({"undefined", "no_data", "waste"})


class GoalError(Exception):
    pass


class GoalValidationError(GoalError):
    pass


class GoalNotFoundError(GoalError):
    pass


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_goal(
        self,
        *,
        user_id: int,
        title: str,
        horizon: str,
        time_group: str,
        target_value: float | None = None,
        unit: str | None = None,
        target_mode: str | None = None,
        preferred_minutes_per_day: int | None = None,
        planning_hint: str | None = None,
        priority: int = 100,
        period_start: date | None = None,
        period_end: date | None = None,
        status: str = "active",
    ) -> Goal:
        title = self._validate_title(title)
        horizon = self.validate_horizon(horizon)
        status = self.validate_status(status)
        time_group = self.validate_time_group(time_group)
        unit = self.validate_unit(unit)
        target_mode = self.validate_target_mode(target_mode)
        self._validate_target_value(target_value)
        self._validate_preferred_minutes(preferred_minutes_per_day)
        self._validate_period(period_start, period_end)

        now = now_tz()
        goal = Goal(
            user_id=user_id,
            title=title,
            horizon=horizon,
            time_group=time_group,
            status=status,
            target_value=target_value,
            unit=unit,
            target_mode=target_mode,
            preferred_minutes_per_day=preferred_minutes_per_day,
            planning_hint=self._clean_optional_text(planning_hint),
            priority=priority,
            period_start=period_start,
            period_end=period_end,
            created_at=now,
            updated_at=now,
        )
        self.session.add(goal)
        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def list_goals(
        self, *, user_id: int, include_archived: bool = False
    ) -> list[Goal]:
        stmt = select(Goal).where(Goal.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(Goal.status != "archived")
        stmt = stmt.order_by(Goal.horizon, Goal.priority, Goal.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def archive_goal(self, *, user_id: int, goal_id: int) -> Goal:
        return await self._set_status(user_id=user_id, goal_id=goal_id, status="archived")

    async def pause_goal(self, *, user_id: int, goal_id: int) -> Goal:
        return await self._set_status(user_id=user_id, goal_id=goal_id, status="paused")

    async def mark_done(self, *, user_id: int, goal_id: int) -> Goal:
        return await self._set_status(user_id=user_id, goal_id=goal_id, status="done")

    async def _set_status(self, *, user_id: int, goal_id: int, status: str) -> Goal:
        status = self.validate_status(status)
        goal = await self._get_goal(user_id=user_id, goal_id=goal_id)
        goal.status = status
        goal.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(goal)
        return goal

    async def _get_goal(self, *, user_id: int, goal_id: int) -> Goal:
        result = await self.session.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
        )
        goal = result.scalar_one_or_none()
        if goal is None:
            raise GoalNotFoundError(f"Goal id={goal_id} not found")
        return goal

    @staticmethod
    def validate_horizon(value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in VALID_GOAL_HORIZONS:
            raise GoalValidationError(
                f"horizon must be one of {sorted(VALID_GOAL_HORIZONS)}"
            )
        return normalized

    @staticmethod
    def validate_status(value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in VALID_GOAL_STATUSES:
            raise GoalValidationError(
                f"status must be one of {sorted(VALID_GOAL_STATUSES)}"
            )
        return normalized

    @staticmethod
    def validate_time_group(value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized in FORBIDDEN_GOAL_TIME_GROUPS or normalized not in TIME_GROUP_CODES:
            allowed = sorted(TIME_GROUP_CODES - FORBIDDEN_GOAL_TIME_GROUPS)
            raise GoalValidationError(f"time_group must be one of {allowed}")
        return normalized

    @staticmethod
    def validate_unit(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in VALID_GOAL_UNITS:
            raise GoalValidationError(f"unit must be one of {sorted(VALID_GOAL_UNITS)}")
        return normalized

    @staticmethod
    def validate_target_mode(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in VALID_GOAL_TARGET_MODES:
            raise GoalValidationError(
                f"target_mode must be one of {sorted(VALID_GOAL_TARGET_MODES)}"
            )
        return normalized

    @staticmethod
    def _validate_title(value: str) -> str:
        title = " ".join((value or "").split())
        if not title:
            raise GoalValidationError("title is required")
        if len(title) > 256:
            raise GoalValidationError("title must be 256 characters or less")
        return title

    @staticmethod
    def _validate_target_value(value: float | None) -> None:
        if value is not None and value <= 0:
            raise GoalValidationError("target_value must be positive")

    @staticmethod
    def _validate_preferred_minutes(value: int | None) -> None:
        if value is not None and value <= 0:
            raise GoalValidationError("preferred_minutes_per_day must be positive")

    @staticmethod
    def _validate_period(start: date | None, end: date | None) -> None:
        if start is not None and end is not None and end < start:
            raise GoalValidationError("period_end must be after period_start")

    @staticmethod
    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(value.split())
        return text or None
