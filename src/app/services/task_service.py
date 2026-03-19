from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db import crud
from app.db.models import Task
from app.services.context_validator import ContextValidator
from app.services.daily_context_service import DailyContextService
from app.services.crisis_stack_service import CrisisStackService
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.validation_result import ConflictType, ValidationStatus

log = logging.getLogger("time-agent.crisis_stack")


@dataclass
class TaskDTO:
    id: int
    title: str
    planned_at: str | None
    duration_min: int
    status: str
    category: str
    context_status: str


class TaskService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_task(
        self,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str = "personal",
        priority_code: str | None = None,
        user_id: int | None = None,
    ) -> TaskDTO:
        context_status = await self._resolve_context_status(
            planned_at=planned_at,
            duration_min=duration_min,
            category=category,
            priority_code=priority_code,
        )

        task = Task(
            title=title,
            planned_at=planned_at,
            duration_min=duration_min,
            status="todo",
            category=category,
            context_status=context_status,
            created_at=now_tz(),
        )

        task = await crud.add_task(self.session, task)
        await self._maybe_trigger_crisis_mode(user_id=user_id)
        return self._to_dto(task)

    async def get_task_by_id(self, task_id: int) -> TaskDTO | None:
        task = await crud.get_task(self.session, task_id)
        if task is None:
            return None
        return self._to_dto(task)

    async def update_task(
        self,
        *,
        task_id: int,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str,
        priority_code: str | None = None,
        user_id: int | None = None,
    ) -> TaskDTO | None:
        context_status = await self._resolve_context_status(
            planned_at=planned_at,
            duration_min=duration_min,
            category=category,
            priority_code=priority_code,
        )

        task = await crud.update_task(
            self.session,
            task_id,
            title=title,
            planned_at=planned_at,
            duration_min=duration_min,
            category=category,
            context_status=context_status,
        )
        if task is None:
            return None

        await self._maybe_trigger_crisis_mode(user_id=user_id)
        return self._to_dto(task)

    async def delete_task(self, task_id: int) -> bool:
        return await crud.delete_task(self.session, task_id)

    async def list_today(self) -> tuple[list[TaskDTO], list[TaskDTO]]:
        now = now_tz()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        timed = await crud.list_tasks_for_day(self.session, day_start, day_end)
        floating = await crud.list_floating_tasks(self.session)

        # Keep existing base order, but apply crisis compatibility rank as secondary
        # precedence for urgent tasks (family A above work) in the active today path.
        timed.sort(
            key=lambda task: (
                task.planned_at,
                self._urgent_precedence_rank(task=task),
                task.id,
            )
        )
        floating.sort(
            key=lambda task: (
                self._urgent_precedence_rank(task=task),
                task.id,
            )
        )

        return [self._to_dto(t, time_only=True) for t in timed], [
            self._to_dto(t, time_only=True) for t in floating
        ]

    @staticmethod
    def _urgent_precedence_rank(*, task: Task) -> int:
        return CrisisStackService.default_urgent_precedence_rank(
            title=task.title,
            category=task.category,
        )

    async def _maybe_trigger_crisis_mode(self, *, user_id: int | None) -> None:
        if user_id is None:
            return

        urgent_tasks_count = await self._count_open_urgent_tasks(user_id=user_id)
        if urgent_tasks_count < 2:
            return

        CrisisStackService().activate_crisis_mode(user_id)
        log.info("Crisis stack activated urgent_tasks=%s", urgent_tasks_count)

    async def _count_open_urgent_tasks(self, *, user_id: int) -> int:
        stmt = (
            select(Task)
            .where(Task.status != "done")
            .where(Task.status != "cancelled")
        )

        task_user_col = getattr(Task, "user_id", None)
        if task_user_col is None:
            log.warning(
                "Crisis trigger skipped: user-scoped task filter is unavailable user_id=%s",
                user_id,
            )
            return 0

        stmt = stmt.where(task_user_col == user_id)

        result = await self.session.execute(stmt)
        tasks = result.scalars().all()
        return sum(1 for task in tasks if CrisisStackService.is_urgent_text(task.title))

    async def _resolve_context_status(
        self,
        *,
        planned_at: datetime | None,
        duration_min: int,
        category: str,
        priority_code: str | None = None,
    ) -> str:
        validator = await self._build_context_validator()

        result = await validator.validate_event(
            start_at=planned_at,
            duration_min=duration_min,
            category=category,
            priority_code=priority_code,
        )

        if result.status == ValidationStatus.VALID:
            return "normal"

        if result.conflict_type == ConflictType.SLEEP:
            return "conflict_sleep"

        if result.conflict_type == ConflictType.SECOND_SLEEP:
            return "conflict_second_sleep"

        if result.conflict_type == ConflictType.PRAYER:
            return "conflict_prayer"

        if result.conflict_type == ConflictType.FAMILY:
            return "conflict_family"

        if result.conflict_type == ConflictType.SIYAM_DAYTIME_LOAD:
            return "conflict_siyam"

        return "normal"

    async def _build_context_validator(self) -> ContextValidator:
        prayer_times_service = PrayerTimesService(self.session)
        routine_service = RoutineService(
            session=self.session,
            prayer_times_service=prayer_times_service,
        )
        rules_service = RulesService(self.session)
        daily_context_service = DailyContextService(self.session)

        return ContextValidator(
            routine_service=routine_service,
            prayer_times_service=prayer_times_service,
            rules_service=rules_service,
            daily_context_service=daily_context_service,
        )

    def _to_dto(self, task: Task, time_only: bool = False) -> TaskDTO:
        if task.planned_at:
            if time_only:
                planned_at = task.planned_at.astimezone(APP_TZ).strftime("%H:%M")
            else:
                planned_at = task.planned_at.astimezone(APP_TZ).strftime(
                    "%Y-%m-%d %H:%M"
                )
        else:
            planned_at = None

        return TaskDTO(
            id=task.id,
            title=task.title,
            planned_at=planned_at,
            duration_min=task.duration_min,
            status=task.status,
            category=task.category,
            context_status=task.context_status,
        )


