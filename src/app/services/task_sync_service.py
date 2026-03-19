from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud
from app.db.task_external_link_repo import TaskExternalLinkRepo
from app.scheduler.jobs import _schedule_same_alert
from app.services.boss_priority_service import BossPriorityService
from app.services.context_validator import ContextValidator
from app.services.daily_context_service import DailyContextService
from app.services.google_calendar_service import (
    ExternalSyncResultDTO,
    GoogleCalendarService,
)
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.task_service import TaskDTO, TaskService
from app.services.task_sync_policy_service import TaskSyncPolicyService
from app.services.validation_result import (
    ConflictType,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)


@dataclass
class CreateTaskWithSyncResultDTO:
    task: TaskDTO | None
    local_created: bool
    google_sync_success: bool
    google_sync_status: str | None
    conflict_names: list[str]
    error_message: str | None
    user_message: str
    validation_result: ValidationResult | None = None


@dataclass
class UpdateTaskWithSyncResultDTO:
    task: TaskDTO | None
    local_updated: bool
    google_sync_success: bool
    google_sync_status: str | None
    conflict_names: list[str]
    error_message: str | None
    user_message: str
    validation_result: ValidationResult | None = None


@dataclass
class DeleteTaskWithSyncResultDTO:
    task_id: int
    local_deleted: bool
    google_sync_success: bool
    google_sync_status: str | None
    error_message: str | None
    user_message: str


class TaskSyncService:
    def __init__(
        self,
        session: AsyncSession,
        gcal_service: GoogleCalendarService,
        scheduler: AsyncIOScheduler | None = None,
        bot=None,
    ):
        self.session = session
        self.gcal_service = gcal_service
        self.scheduler = scheduler
        self.bot = bot
        self.task_service = TaskService(session)
        self.rules_service = RulesService(session)
        self.link_repo = TaskExternalLinkRepo(session)
        self.policy_service = TaskSyncPolicyService()

    async def create_task_with_google_sync(
        self,
        *,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str = "personal",
        user_id: int | None = None,
        skip_context_validation: bool = False,
    ) -> CreateTaskWithSyncResultDTO:
        conflicts: list[str] = []
        normalized_category = self.policy_service.normalize_category(category)
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
                return CreateTaskWithSyncResultDTO(
                    task=None,
                    local_created=False,
                    google_sync_success=False,
                    google_sync_status=None,
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
                return CreateTaskWithSyncResultDTO(
                    task=None,
                    local_created=False,
                    google_sync_success=False,
                    google_sync_status=None,
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
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return CreateTaskWithSyncResultDTO(
                task=task,
                local_created=True,
                google_sync_success=False,
                google_sync_status=None,
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        provider = "google_calendar"
        policy = self.policy_service.decide(normalized_category)

        if not policy.sync_allowed:
            await self.link_repo.create_skipped(
                task_id=task.id,
                provider=provider,
                skip_reason=policy.skip_reason or "category_policy",
            )

            message = (
                f"{policy.user_message_template}\n"
                f"#{task.id} {task.title} — в {task.planned_at}, "
                f"{task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return CreateTaskWithSyncResultDTO(
                task=task,
                local_created=True,
                google_sync_success=False,
                google_sync_status=policy.sync_status_if_skipped,
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        already_synced = await self.link_repo.exists_synced(task.id, provider)
        if already_synced:
            message = (
                f"✅ Добавлено: #{task.id} {task.title} — в {task.planned_at}, "
                f"{task.duration_min} мин.\n"
                "Google Calendar уже синхронизирован ✅"
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return CreateTaskWithSyncResultDTO(
                task=task,
                local_created=True,
                google_sync_success=True,
                google_sync_status="synced",
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        await self.link_repo.create_pending(task.id, provider)

        sync_result: ExternalSyncResultDTO = await self.gcal_service.create_event(
            task_id=task.id,
            title=task.title,
            start_at=planned_at,
            duration_min=duration_min,
            category=normalized_category,
            description=f"Local task #{task.id} from Telegram Time-Agent",
            calendar_id="primary",
        )

        if sync_result.success and sync_result.external_id:
            await self.link_repo.mark_synced(
                task_id=task.id,
                provider=provider,
                external_id=sync_result.external_id,
                calendar_id=sync_result.external_calendar_id or "primary",
            )

            message = (
                "✅ Задача создана и синхронизирована с Google Calendar.\n"
                f"#{task.id} {task.title} — в {task.planned_at}, "
                f"{task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return CreateTaskWithSyncResultDTO(
                task=task,
                local_created=True,
                google_sync_success=True,
                google_sync_status="synced",
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        error_text = sync_result.error_message or "Unknown Google sync error"

        await self.link_repo.mark_failed(
            task_id=task.id,
            provider=provider,
            error_text=error_text,
        )

        message = (
            "✅ Задача сохранена локально. "
            "Синхронизация с Google временно недоступна.\n"
            f"#{task.id} {task.title} — в {task.planned_at}, "
            f"{task.duration_min} мин."
        )
        if boss_alert_message:
            message = f"{message}\n{boss_alert_message}"

        return CreateTaskWithSyncResultDTO(
            task=task,
            local_created=True,
            google_sync_success=False,
            google_sync_status="sync_failed",
            conflict_names=[],
            error_message=error_text,
            user_message=message,
            validation_result=validation_result,
        )

    async def sync_update_task(
        self,
        *,
        task_id: int,
        title: str,
        planned_at: datetime | None,
        duration_min: int,
        category: str,
    ) -> UpdateTaskWithSyncResultDTO:
        provider = "google_calendar"
        conflicts: list[str] = []

        old_task = await self.task_service.get_task_by_id(task_id)
        if old_task is None:
            return UpdateTaskWithSyncResultDTO(
                task=None,
                local_updated=False,
                google_sync_success=False,
                google_sync_status=None,
                conflict_names=[],
                error_message="Task not found",
                user_message=f"❌ Задача #{task_id} не найдена.",
                validation_result=None,
            )

        normalized_new_category = self.policy_service.normalize_category(category)
        old_policy = self.policy_service.decide(old_task.category)
        new_policy = self.policy_service.decide(normalized_new_category)
        priority_code = self._resolve_priority_code(title)

        validation_result = await self._validate_context(
            planned_at=planned_at,
            duration_min=duration_min,
            category=normalized_new_category,
            priority_code=priority_code,
        )
        if (
            validation_result is not None
            and validation_result.status != ValidationStatus.VALID
        ):
            return UpdateTaskWithSyncResultDTO(
                task=None,
                local_updated=False,
                google_sync_success=False,
                google_sync_status=None,
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
                return UpdateTaskWithSyncResultDTO(
                    task=None,
                    local_updated=False,
                    google_sync_success=False,
                    google_sync_status=None,
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
            category=normalized_new_category,
            priority_code=priority_code,
        )

        if updated_task is None:
            return UpdateTaskWithSyncResultDTO(
                task=None,
                local_updated=False,
                google_sync_success=False,
                google_sync_status=None,
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

        link = await self.link_repo.get_by_task_and_provider(task_id, provider)

        if planned_at is None:
            if link and link.external_id and old_policy.sync_allowed:
                await self.link_repo.mark_delete_pending(task_id, provider)

                delete_result = await self.gcal_service.delete_event(
                    external_id=link.external_id,
                    calendar_id=link.external_calendar_id or "primary",
                )

                if delete_result.success:
                    await self.link_repo.mark_deleted_external(task_id, provider)
                    message = (
                        "✅ Задача обновлена. "
                        "Внешнее событие удалено из Google Calendar, "
                        "потому что задача теперь без времени.\n"
                        f"#{updated_task.id} {updated_task.title} — без времени, "
                        f"{updated_task.duration_min} мин."
                    )
                    if boss_alert_message:
                        message = f"{message}\n{boss_alert_message}"

                    return UpdateTaskWithSyncResultDTO(
                        task=updated_task,
                        local_updated=True,
                        google_sync_success=True,
                        google_sync_status="deleted_external",
                        conflict_names=[],
                        error_message=None,
                        user_message=message,
                        validation_result=validation_result,
                    )

                error_text = (
                    delete_result.error_message or "Unknown Google delete error"
                )
                await self.link_repo.mark_delete_failed(
                    task_id,
                    provider,
                    error_text,
                )

                message = (
                    "✅ Задача обновлена локально, но удаление старого события "
                    "из Google временно недоступно.\n"
                    f"#{updated_task.id} {updated_task.title} — без времени, "
                    f"{updated_task.duration_min} мин."
                )
                if boss_alert_message:
                    message = f"{message}\n{boss_alert_message}"

                return UpdateTaskWithSyncResultDTO(
                    task=updated_task,
                    local_updated=True,
                    google_sync_success=False,
                    google_sync_status="delete_failed",
                    conflict_names=[],
                    error_message=error_text,
                    user_message=message,
                    validation_result=validation_result,
                )

            message = (
                f"✅ Задача обновлена: #{updated_task.id} {updated_task.title} "
                f"— без времени, {updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=False,
                google_sync_status=None,
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        if not old_policy.sync_allowed and not new_policy.sync_allowed:
            await self.link_repo.create_skipped(
                task_id=updated_task.id,
                provider=provider,
                skip_reason=new_policy.skip_reason or "category_policy",
            )
            message = (
                f"{new_policy.user_message_template}\n"
                f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                f"{updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=False,
                google_sync_status="skipped_by_policy",
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        if not old_policy.sync_allowed and new_policy.sync_allowed:
            await self.link_repo.create_pending(updated_task.id, provider)

            create_result = await self.gcal_service.create_event(
                task_id=updated_task.id,
                title=updated_task.title,
                start_at=planned_at,
                duration_min=duration_min,
                category=normalized_new_category,
                description=f"Local task #{updated_task.id} from Telegram Time-Agent",
                calendar_id="primary",
            )

            if create_result.success and create_result.external_id:
                await self.link_repo.mark_synced(
                    task_id=updated_task.id,
                    provider=provider,
                    external_id=create_result.external_id,
                    calendar_id=create_result.external_calendar_id or "primary",
                )

                message = (
                    "✅ Задача обновлена и синхронизирована с Google Calendar.\n"
                    f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                    f"{updated_task.duration_min} мин."
                )
                if boss_alert_message:
                    message = f"{message}\n{boss_alert_message}"

                return UpdateTaskWithSyncResultDTO(
                    task=updated_task,
                    local_updated=True,
                    google_sync_success=True,
                    google_sync_status="synced",
                    conflict_names=[],
                    error_message=None,
                    user_message=message,
                    validation_result=validation_result,
                )

            error_text = create_result.error_message or "Unknown Google create error"
            await self.link_repo.mark_failed(
                task_id=updated_task.id,
                provider=provider,
                error_text=error_text,
            )

            message = (
                "✅ Задача обновлена локально. "
                "Синхронизация с Google временно недоступна.\n"
                f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                f"{updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=False,
                google_sync_status="sync_failed",
                conflict_names=[],
                error_message=error_text,
                user_message=message,
                validation_result=validation_result,
            )

        if old_policy.sync_allowed and not new_policy.sync_allowed:
            if link and link.external_id:
                await self.link_repo.mark_delete_pending(task_id, provider)

                delete_result = await self.gcal_service.delete_event(
                    external_id=link.external_id,
                    calendar_id=link.external_calendar_id or "primary",
                )

                if delete_result.success:
                    await self.link_repo.mark_deleted_external(task_id, provider)
                    message = (
                        f"{new_policy.user_message_template}\n"
                        "Внешняя синхронизация отключена, событие удалено из Google Calendar.\n"
                        f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                        f"{updated_task.duration_min} мин."
                    )
                    if boss_alert_message:
                        message = f"{message}\n{boss_alert_message}"

                    return UpdateTaskWithSyncResultDTO(
                        task=updated_task,
                        local_updated=True,
                        google_sync_success=True,
                        google_sync_status="deleted_external",
                        conflict_names=[],
                        error_message=None,
                        user_message=message,
                        validation_result=validation_result,
                    )

                error_text = (
                    delete_result.error_message or "Unknown Google delete error"
                )
                await self.link_repo.mark_delete_failed(
                    task_id,
                    provider,
                    error_text,
                )

                message = (
                    f"{new_policy.user_message_template}\n"
                    "⚠️ Но старое событие в Google пока не удалось удалить."
                )
                if boss_alert_message:
                    message = f"{message}\n{boss_alert_message}"

                return UpdateTaskWithSyncResultDTO(
                    task=updated_task,
                    local_updated=True,
                    google_sync_success=False,
                    google_sync_status="delete_failed",
                    conflict_names=[],
                    error_message=error_text,
                    user_message=message,
                    validation_result=validation_result,
                )

            await self.link_repo.create_skipped(
                task_id=updated_task.id,
                provider=provider,
                skip_reason=new_policy.skip_reason or "category_policy",
            )

            message = (
                f"{new_policy.user_message_template}\n"
                f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                f"{updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=False,
                google_sync_status="skipped_by_policy",
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        if link is None or not link.external_id:
            await self.link_repo.create_pending(updated_task.id, provider)

            create_result = await self.gcal_service.create_event(
                task_id=updated_task.id,
                title=updated_task.title,
                start_at=planned_at,
                duration_min=duration_min,
                category=normalized_new_category,
                description=f"Local task #{updated_task.id} from Telegram Time-Agent",
                calendar_id="primary",
            )

            if create_result.success and create_result.external_id:
                await self.link_repo.mark_synced(
                    task_id=updated_task.id,
                    provider=provider,
                    external_id=create_result.external_id,
                    calendar_id=create_result.external_calendar_id or "primary",
                )

                message = (
                    "✅ Задача обновлена и синхронизирована с Google Calendar.\n"
                    f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                    f"{updated_task.duration_min} мин."
                )
                if boss_alert_message:
                    message = f"{message}\n{boss_alert_message}"

                return UpdateTaskWithSyncResultDTO(
                    task=updated_task,
                    local_updated=True,
                    google_sync_success=True,
                    google_sync_status="synced",
                    conflict_names=[],
                    error_message=None,
                    user_message=message,
                    validation_result=validation_result,
                )

            error_text = create_result.error_message or "Unknown Google create error"
            await self.link_repo.mark_failed(
                task_id=updated_task.id,
                provider=provider,
                error_text=error_text,
            )

            message = (
                "✅ Задача обновлена локально. "
                "Синхронизация с Google временно недоступна.\n"
                f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                f"{updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=False,
                google_sync_status="sync_failed",
                conflict_names=[],
                error_message=error_text,
                user_message=message,
                validation_result=validation_result,
            )

        await self.link_repo.mark_update_pending(updated_task.id, provider)

        update_result = await self.gcal_service.update_event(
            task_id=updated_task.id,
            external_id=link.external_id,
            title=updated_task.title,
            start_at=planned_at,
            duration_min=duration_min,
            category=normalized_new_category,
            description=f"Local task #{updated_task.id} from Telegram Time-Agent",
            calendar_id=link.external_calendar_id or "primary",
        )

        if update_result.success:
            await self.link_repo.mark_synced(
                task_id=updated_task.id,
                provider=provider,
                external_id=link.external_id,
                calendar_id=link.external_calendar_id or "primary",
            )

            message = (
                "✅ Задача обновлена и синхронизирована с Google Calendar.\n"
                f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
                f"{updated_task.duration_min} мин."
            )
            if boss_alert_message:
                message = f"{message}\n{boss_alert_message}"

            return UpdateTaskWithSyncResultDTO(
                task=updated_task,
                local_updated=True,
                google_sync_success=True,
                google_sync_status="synced",
                conflict_names=[],
                error_message=None,
                user_message=message,
                validation_result=validation_result,
            )

        error_text = update_result.error_message or "Unknown Google update error"
        await self.link_repo.mark_update_failed(
            updated_task.id,
            provider,
            error_text,
        )

        message = (
            "✅ Задача обновлена локально. "
            "Синхронизация изменений с Google временно недоступна.\n"
            f"#{updated_task.id} {updated_task.title} — в {updated_task.planned_at}, "
            f"{updated_task.duration_min} мин."
        )
        if boss_alert_message:
            message = f"{message}\n{boss_alert_message}"

        return UpdateTaskWithSyncResultDTO(
            task=updated_task,
            local_updated=True,
            google_sync_success=False,
            google_sync_status="update_failed",
            conflict_names=[],
            error_message=error_text,
            user_message=message,
            validation_result=validation_result,
        )

    async def sync_delete_task(
        self,
        *,
        task_id: int,
    ) -> DeleteTaskWithSyncResultDTO:
        provider = "google_calendar"

        task = await self.task_service.get_task_by_id(task_id)
        if task is None:
            return DeleteTaskWithSyncResultDTO(
                task_id=task_id,
                local_deleted=False,
                google_sync_success=False,
                google_sync_status=None,
                error_message="Task not found",
                user_message=f"❌ Задача #{task_id} не найдена.",
            )

        await self._cleanup_boss_alert_if_needed(
            task_id=task_id,
            title=task.title,
            reason="task_deleted",
        )

        policy = self.policy_service.decide(task.category)
        link = await self.link_repo.get_by_task_and_provider(task_id, provider)

        if (
            not policy.sync_allowed
            or link is None
            or not link.external_id
            or link.sync_status in {"skipped_by_policy", "deleted_external"}
        ):
            deleted = await self.task_service.delete_task(task_id)
            if not deleted:
                return DeleteTaskWithSyncResultDTO(
                    task_id=task_id,
                    local_deleted=False,
                    google_sync_success=False,
                    google_sync_status=None,
                    error_message="Local delete failed",
                    user_message=f"❌ Не удалось удалить задачу #{task_id}.",
                )

            return DeleteTaskWithSyncResultDTO(
                task_id=task_id,
                local_deleted=True,
                google_sync_success=False,
                google_sync_status=None,
                error_message=None,
                user_message=f"✅ Задача #{task_id} удалена локально.",
            )

        await self.link_repo.mark_delete_pending(task_id, provider)

        delete_result = await self.gcal_service.delete_event(
            external_id=link.external_id,
            calendar_id=link.external_calendar_id or "primary",
        )

        if delete_result.success:
            await self.link_repo.mark_deleted_external(task_id, provider)
            deleted = await self.task_service.delete_task(task_id)

            if not deleted:
                return DeleteTaskWithSyncResultDTO(
                    task_id=task_id,
                    local_deleted=False,
                    google_sync_success=True,
                    google_sync_status="deleted_external",
                    error_message="Local delete failed after Google delete",
                    user_message=(
                        f"⚠️ Событие в Google удалено, но локальную задачу #{task_id} "
                        "не удалось удалить."
                    ),
                )

            return DeleteTaskWithSyncResultDTO(
                task_id=task_id,
                local_deleted=True,
                google_sync_success=True,
                google_sync_status="deleted_external",
                error_message=None,
                user_message=(
                    f"✅ Задача #{task_id} удалена локально и из Google Calendar."
                ),
            )

        error_text = delete_result.error_message or "Unknown Google delete error"
        await self.link_repo.mark_delete_failed(
            task_id,
            provider,
            error_text,
        )

        deleted = await self.task_service.delete_task(task_id)

        if not deleted:
            return DeleteTaskWithSyncResultDTO(
                task_id=task_id,
                local_deleted=False,
                google_sync_success=False,
                google_sync_status="delete_failed",
                error_message=error_text,
                user_message=(
                    f"⚠️ Не удалось удалить задачу #{task_id} локально. "
                    "И синхронизация удаления с Google тоже не удалась."
                ),
            )

        return DeleteTaskWithSyncResultDTO(
            task_id=task_id,
            local_deleted=True,
            google_sync_success=False,
            google_sync_status="delete_failed",
            error_message=error_text,
            user_message=(
                f"✅ Задача #{task_id} удалена локально. "
                "Удаление из Google Calendar временно недоступно."
            ),
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

        chat_id = await self._resolve_owner_chat_id()
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

    async def _resolve_owner_chat_id(self) -> int | None:
        try:
            _ = self.gcal_service.bot_notify_fn
        except AttributeError:
            pass

        try:
            from app.config import load_config

            cfg = load_config()
            return cfg.allowed_telegram_id
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
