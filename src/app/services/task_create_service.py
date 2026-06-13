from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from app.scheduler.jobs import _schedule_same_alert
from app.services.boss_priority_service import BossPriorityService
from app.services.categories import KNOWN_CATEGORIES
from app.services.context_validator import ContextValidator
from app.services.daily_context_service import DailyContextService
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.task_service import TaskDTO, TaskService
from app.services.validation_result import (
    ConflictType,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)


@dataclass
class CreateTaskResultDTO:
    task: TaskDTO | None
    local_created: bool
    conflict_names: list[str]
    error_message: str | None
    user_message: str
    validation_result: ValidationResult | None = None


@dataclass
class UpdateTaskResultDTO:
    task: TaskDTO | None
    local_updated: bool
    conflict_names: list[str]
    error_message: str | None
    user_message: str
    validation_result: ValidationResult | None = None


@dataclass
class DeleteTaskResultDTO:
    task_id: int
    local_deleted: bool
    error_message: str | None
    user_message: str


class TaskCreateService:
    def __init__(
        self,
        session: AsyncSession,
        scheduler: AsyncIOScheduler | None = None,
        bot=None,
    ):
        self.session = session
        self.scheduler = scheduler
        self.bot = bot
        self.task_service = TaskService(session)
        self.rules_service = RulesService(session)

    async def create_task(
        self,
        *,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str = "personal",
        user_id: int | None = None,
        skip_context_validation: bool = False,
    ) -> CreateTaskResultDTO:
        normalized_category = self._normalize_category(category)
        priority_code = self._resolve_priority_code(title)

        validation_result: ValidationResult | None = None
        if not skip_context_validation:
            validation_result = await self._validate_context(
                planned_at=planned_at,
                duration_min=duration_min,
                category=normalized_category,
                priority_code=priority_code,
            )
            if (
                validation_result is not None
                and validation_result.status != ValidationStatus.VALID
            ):
                return CreateTaskResultDTO(
                    task=None,
                    local_created=False,
                    conflict_names=[],
                    error_message=None,
                    user_message=self._format_validation_message(validation_result),
                    validation_result=validation_result,
                )

        if planned_at is not None and not skip_context_validation:
            conflict_dtos = await self.rules_service.check_conflicts(
                planned_at,
                duration_min,
            )
            conflicts = [c.name for c in conflict_dtos]

            if conflicts:
                names = ", ".join(conflicts)
                return CreateTaskResultDTO(
                    task=None,
                    local_created=False,
                    conflict_names=conflicts,
                    error_message=None,
                    user_message=(
                        "❌ Задача не создана: пересечение с защищённым слотом: "
                        f"{names}"
                    ),
                    validation_result=None,
                )

        task = await self.task_service.create_task(
            title=title,
            planned_at=planned_at,
            duration_min=duration_min,
            category=normalized_category,
            priority_code=priority_code,
            user_id=user_id,
        )

        boss_alert_message = await self._maybe_create_boss_alert(
            task_id=task.id,
            title=task.title,
            deadline_at=planned_at,
        )

        if planned_at is None:
            message = (
                f"✅ Добавлено: #{task.id} {task.title} — без времени, "
                f"{task.duration_min} мин."
            )
        else:
            message = (
                f"✅ Добавлено: #{task.id} {task.title} — в {task.planned_at}, "
                f"{task.duration_min} мин."
            )

        if boss_alert_message:
            message = f"{message}\n{boss_alert_message}"

        return CreateTaskResultDTO(
            task=task,
            local_created=True,
            conflict_names=[],
            error_message=None,
            user_message=message,
            validation_result=validation_result,
        )

    async def update_task(
        self,
        *,
        task_id: int,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str,
        user_id: int | None = None,
    ) -> UpdateTaskResultDTO:
        old_task = await self.task_service.get_task_by_id(task_id)
        if old_task is None:
            return UpdateTaskResultDTO(
                task=None,
                local_updated=False,
                conflict_names=[],
                error_message="Task not found",
                user_message=f"❌ Задача #{task_id} не найдена.",
                validation_result=None,
            )

        normalized_category = self._normalize_category(category)
        priority_code = self._resolve_priority_code(title)

        validation_result = await self._validate_context(
            planned_at=planned_at,
            duration_min=duration_min,
            category=normalized_category,
            priority_code=priority_code,
        )
        if (
            validation_result is not None
            and validation_result.status != ValidationStatus.VALID
        ):
            return UpdateTaskResultDTO(
                task=None,
                local_updated=False,
                conflict_names=[],
                error_message=None,
                user_message=self._format_validation_message(validation_result),
                validation_result=validation_result,
            )

        if planned_at is not None:
            conflict_dtos = await self.rules_service.check_conflicts(
                planned_at,
                duration_min,
            )
            conflicts = [c.name for c in conflict_dtos]

            if conflicts:
                names = ", ".join(conflicts)
                return UpdateTaskResultDTO(
                    task=None,
                    local_updated=False,
                    conflict_names=conflicts,
                    error_message=None,
                    user_message=(
                        "❌ Задача не изменена: пересечение с защищённым слотом: "
                        f"{names}"
                    ),
                    validation_result=None,
                )

        updated_task = await self.task_service.update_task(
            task_id=task_id,
            title=title,
            planned_at=planned_at,
            duration_min=duration_min,
            category=normalized_category,
            priority_code=priority_code,
            user_id=user_id,
        )

        if updated_task is None:
            return UpdateTaskResultDTO(
                task=None,
                local_updated=False,
                conflict_names=[],
                error_message="Task update failed",
                user_message=f"❌ Не удалось обновить задачу #{task_id}.",
                validation_result=validation_result,
            )

        boss_alert_message = await self._maybe_create_boss_alert(
            task_id=updated_task.id,
            title=updated_task.title,
            deadline_at=planned_at,
        )

        if planned_at is None:
            message = (
                f"✅ Задача обновлена: #{updated_task.id} {updated_task.title} "
                f"— без времени, {updated_task.duration_min} мин."
            )
        else:
            message = (
                f"✅ Задача обновлена: #{updated_task.id} {updated_task.title} "
                f"— в {updated_task.planned_at}, {updated_task.duration_min} мин."
            )

        if boss_alert_message:
            message = f"{message}\n{boss_alert_message}"

        return UpdateTaskResultDTO(
            task=updated_task,
            local_updated=True,
            conflict_names=[],
            error_message=None,
            user_message=message,
            validation_result=validation_result,
        )

    async def delete_task(self, *, task_id: int) -> DeleteTaskResultDTO:
        task = await self.task_service.get_task_by_id(task_id)
        if task is None:
            return DeleteTaskResultDTO(
                task_id=task_id,
                local_deleted=False,
                error_message="Task not found",
                user_message=f"❌ Задача #{task_id} не найдена.",
            )

        await self._cleanup_boss_alert_if_needed(
            task_id=task_id,
            title=task.title,
            reason="task_deleted",
        )

        deleted = await self.task_service.delete_task(task_id)
        if not deleted:
            return DeleteTaskResultDTO(
                task_id=task_id,
                local_deleted=False,
                error_message="Local delete failed",
                user_message=f"❌ Не удалось удалить задачу #{task_id}.",
            )

        return DeleteTaskResultDTO(
            task_id=task_id,
            local_deleted=True,
            error_message=None,
            user_message=f"✅ Задача #{task_id} удалена.",
        )

    async def _validate_context(
        self,
        *,
        planned_at: datetime | None,
        duration_min: int,
        category: str,
        priority_code: str | None,
    ) -> ValidationResult | None:
        validator = await self._build_context_validator()
        return await validator.validate_event(
            start_at=planned_at,
            duration_min=duration_min,
            category=category,
            priority_code=priority_code,
        )

    async def _build_context_validator(self) -> ContextValidator:
        prayer_times_service = PrayerTimesService(self.session)
        routine_service = RoutineService(
            session=self.session,
            prayer_times_service=prayer_times_service,
        )
        rules_service = RulesService(self.session)

        return ContextValidator(
            routine_service=routine_service,
            prayer_times_service=prayer_times_service,
            rules_service=rules_service,
            daily_context_service=DailyContextService(self.session),
        )

    async def _maybe_create_boss_alert(
        self,
        *,
        task_id: int,
        title: str,
        deadline_at: datetime | None,
    ) -> str | None:
        boss_service = BossPriorityService(self.session)
        decision = await boss_service.evaluate_task(
            title=title,
            deadline_at=deadline_at,
        )

        if not decision.is_boss_task:
            await boss_service.close_active_alert_for_task(
                task_id=task_id,
                reason="boss_marker_removed",
            )
            await self._remove_scheduled_alert_job(task_id=task_id)
            return None

        chat_id = self._resolve_owner_chat_id()
        if chat_id is None:
            return "⚠️ Boss alert не создан: ALLOWED_TELEGRAM_ID не настроен."

        alert = await boss_service.create_or_update_alert(
            chat_id=chat_id,
            task_id=task_id,
            title=title,
            deadline_at=deadline_at,
        )
        if alert is None:
            return None

        self._schedule_boss_alert(alert)

        if decision.should_wake_now:
            return "🔥 Boss alert поставлен в persistent queue."
        if decision.delayed_until is not None:
            return (
                "💤 Boss alert поставлен в persistent queue и отложен до окна пробуждения: "
                f"{decision.delayed_until.strftime('%H:%M')}."
            )

        return "🔥 Boss alert поставлен в persistent queue."

    async def _cleanup_boss_alert_if_needed(
        self,
        *,
        task_id: int,
        title: str,
        reason: str,
    ) -> None:
        boss_service = BossPriorityService(self.session)
        if not boss_service._is_boss_task(title):
            return

        closed = await boss_service.close_active_alert_for_task(
            task_id=task_id,
            reason=reason,
        )
        if closed:
            await self._remove_scheduled_alert_job(task_id=task_id)

    def _schedule_boss_alert(self, alert) -> None:
        if self.scheduler is None or self.bot is None:
            return

        _schedule_same_alert(
            alert_id=alert.id,
            scheduled_for=alert.scheduled_for,
            scheduler=self.scheduler,
            bot=self.bot,
        )

    async def _remove_scheduled_alert_job(self, *, task_id: int) -> None:
        if self.scheduler is None:
            return

        alert = await crud.get_active_alert_by_key(
            self.session,
            alert_type="boss_critical",
            entity_type="task",
            entity_id=str(task_id),
        )

        if alert is not None:
            self._remove_job_by_alert_id(alert.id)
            return

        latest = await crud.get_latest_alert_by_entity(
            self.session,
            alert_type="boss_critical",
            entity_type="task",
            entity_id=str(task_id),
        )
        if latest is not None:
            self._remove_job_by_alert_id(latest.id)

    def _remove_job_by_alert_id(self, alert_id: int) -> None:
        if self.scheduler is None:
            return

        job_id = f"alert_{alert_id}"
        job = self.scheduler.get_job(job_id)
        if job is None:
            return

        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

    @staticmethod
    def _resolve_priority_code(title: str) -> str | None:
        if "🔥" in title:
            return "BOSS_CRITICAL"
        return None

    @staticmethod
    def _normalize_category(category: str | None) -> str:
        raw = (category or "").strip().lower()
        return raw if raw in KNOWN_CATEGORIES else "other"

    @staticmethod
    def _resolve_owner_chat_id() -> int | None:
        try:
            from app.config import load_config
            return load_config().allowed_telegram_id
        except Exception:
            return None

    def _format_validation_message(self, result: ValidationResult) -> str:
        base = result.message or "Задача не прошла контекстную проверку."

        has_suggested_slot = (
            result.suggested_slot_start is not None
            and result.suggested_slot_end is not None
        )

        if has_suggested_slot:
            slot_text = (
                f"{result.suggested_slot_start.strftime('%H:%M')}"
                f"–{result.suggested_slot_end.strftime('%H:%M')}"
            )

            if result.severity == ValidationSeverity.WARNING:
                return f"⚠️ {base}\nПеренести в окно: {slot_text}?"

            if result.severity == ValidationSeverity.HARD_BLOCK:
                return (
                    f"⛔ {base}\n"
                    f"Свободное окно: {slot_text}\n"
                    "Нужно подтверждение пользователя."
                )

        if result.conflict_type == ConflictType.PRAYER:
            return f"⚠️ {base}"

        if result.conflict_type == ConflictType.SLEEP:
            return f"⛔ {base}\nНужно подтверждение пользователя."

        if result.conflict_type == ConflictType.SECOND_SLEEP:
            return f"⛔ {base}\nНужно подтверждение пользователя."

        if result.conflict_type == ConflictType.FAMILY:
            return f"⛔ {base}\nНужно подтверждение пользователя."

        if result.conflict_type == ConflictType.SIYAM_DAYTIME_LOAD:
            return f"⚠️ {base}"

        if result.severity == ValidationSeverity.WARNING:
            return f"⚠️ {base}"

        if result.severity == ValidationSeverity.HARD_BLOCK:
            return f"⛔ {base}\nНужно подтверждение пользователя."

        return f"❌ {base}"
