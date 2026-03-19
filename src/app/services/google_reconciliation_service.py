from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db import crud
from app.db.task_external_link_repo import TaskExternalLinkRepo
from app.integrations.google.dto import (
    GoogleConflictItemDTO,
    GoogleEventDTO,
    GooglePullSummaryDTO,
)
from app.services.context_validator import ContextValidator
from app.services.google_calendar_service import GoogleCalendarService
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.task_service import TaskDTO, TaskService
from app.services.validation_result import ConflictType, ValidationStatus


class GoogleReconciliationService:
    RELEVANT_CONFLICT_SYNC_STATUSES = {
        "imported_from_google",
        "synced",
    }

    def __init__(
        self,
        session: AsyncSession,
        gcal_service: GoogleCalendarService,
    ) -> None:
        self.session = session
        self.gcal_service = gcal_service
        self.task_service = TaskService(session)
        self.link_repo = TaskExternalLinkRepo(session)

    async def pull_and_reconcile(
        self,
        *,
        days_back: int = 1,
        days_forward: int = 7,
        calendar_id: str = "primary",
    ) -> GooglePullSummaryDTO:
        now = now_tz()
        time_min = datetime.combine(
            (now - timedelta(days=days_back)).date(),
            time.min,
            tzinfo=APP_TZ,
        )
        time_max = datetime.combine(
            (now + timedelta(days=days_forward)).date(),
            time.max,
            tzinfo=APP_TZ,
        )

        events = await self.gcal_service.list_events(
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
        )

        summary = GooglePullSummaryDTO()

        for event in events:
            await self._process_event(event, summary)

        return summary

    async def build_conflict_action_text(self, *, task_id: int) -> str | None:
        task = await crud.get_task(self.session, task_id)
        if task is None or task.planned_at is None:
            return None

        duration_min = task.duration_min
        result = await self._get_relevant_conflict_result(
            task_id=task_id,
            start_at=task.planned_at,
            duration_min=duration_min,
            category=task.category,
        )
        if result is None:
            return None

        conflict_label = self._format_conflict_label(result.conflict_type)
        event_time = task.planned_at.astimezone(APP_TZ).strftime("%Y-%m-%d %H:%M")
        conflict_text = result.message or "Обнаружен контекстный конфликт."

        return (
            f"⚠️ Событие из Google Calendar конфликтует с {conflict_label}.\n\n"
            f"Событие: {task.title}\n"
            f"Время: {event_time}\n"
            f"Конфликт: {conflict_text}\n\n"
            "Что делаем?"
        )

    async def build_safe_slot_message(self, *, task_id: int) -> str:
        task = await crud.get_task(self.session, task_id)
        if task is None:
            return "❌ Локальная задача не найдена."

        if task.planned_at is None:
            return "❌ У задачи нет времени, безопасный слот не требуется."

        result = await self._get_relevant_conflict_result(
            task_id=task_id,
            start_at=task.planned_at,
            duration_min=task.duration_min,
            category=task.category,
        )

        if result is None:
            return "✅ Сейчас конфликт уже не актуален."

        if result.suggested_slot_start is None or result.suggested_slot_end is None:
            return (
                "⚠️ Безопасный слот пока не найден в пределах окна поиска.\n"
                "Событие можно оставить как есть или перенести вручную."
            )

        slot_text = (
            f"{result.suggested_slot_start.strftime('%Y-%m-%d %H:%M')}"
            f"–{result.suggested_slot_end.strftime('%H:%M')}"
        )

        return (
            "🟢 Безопасный слот найден.\n"
            f"Событие: {task.title}\n"
            f"Свободное окно: {slot_text}\n\n"
            "Этот слот уже прошёл полную центральную валидацию "
            "(намаз, буфер, сон, второй сон, protected slot, siyam)."
        )

    async def _process_event(
        self,
        event: GoogleEventDTO,
        summary: GooglePullSummaryDTO,
    ) -> None:
        provider = "google_calendar"

        if event.status == "cancelled":
            summary.skipped += 1
            summary.notes.append(f"- skipped cancelled: {event.summary}")
            return

        if event.all_day:
            summary.skipped += 1
            summary.notes.append(f"- skipped all-day: {event.summary}")
            return

        if event.start_at is None:
            summary.skipped += 1
            summary.notes.append(f"- skipped no-start: {event.summary}")
            return

        if (
            event.source_marker == "telegram_time_agent"
            and event.local_task_id is not None
        ):
            summary.skipped_echo += 1
            return

        duration_min = self._calc_duration_min(event)

        existing_link = await self.link_repo.get_by_external_id(
            provider=provider,
            external_id=event.external_id,
        )

        if existing_link is not None:
            existing_task = await self.task_service.get_task_by_id(
                existing_link.task_id
            )
            if existing_task is None:
                summary.skipped += 1
                summary.notes.append(
                    f"- orphan link without local task: {event.summary}"
                )
                return

            if self._is_unchanged(existing_task, event, duration_min):
                summary.skipped += 1
                summary.notes.append(f"- skip unchanged: {event.summary}")
                return

            updated_task = await self.task_service.update_task(
                task_id=existing_link.task_id,
                title=event.summary,
                planned_at=event.start_at,
                duration_min=duration_min,
                category="other",
            )

            if updated_task is None:
                summary.skipped += 1
                summary.notes.append(f"- failed update: {event.summary}")
                return

            summary.updated += 1
            await self._accumulate_conflict(
                task_id=updated_task.id,
                event=event,
                context_status=updated_task.context_status,
                duration_min=duration_min,
                category=updated_task.category,
                summary=summary,
            )
            return

        created_task = await self.task_service.create_task(
            title=event.summary,
            planned_at=event.start_at,
            duration_min=duration_min,
            category="other",
        )

        await self.link_repo.create_imported_from_google(
            task_id=created_task.id,
            provider=provider,
            external_id=event.external_id,
            calendar_id=event.calendar_id,
        )

        summary.imported += 1
        await self._accumulate_conflict(
            task_id=created_task.id,
            event=event,
            context_status=created_task.context_status,
            duration_min=duration_min,
            category=created_task.category,
            summary=summary,
        )

    @staticmethod
    def _calc_duration_min(event: GoogleEventDTO) -> int:
        if event.start_at is None or event.end_at is None:
            return 60

        delta = event.end_at - event.start_at
        minutes = int(delta.total_seconds() // 60)

        if minutes <= 0:
            return 60

        return minutes

    @staticmethod
    def _is_unchanged(
        existing_task: TaskDTO,
        event: GoogleEventDTO,
        duration_min: int,
    ) -> bool:
        event_planned_at = None
        if event.start_at is not None:
            event_planned_at = event.start_at.astimezone(APP_TZ).strftime(
                "%Y-%m-%d %H:%M"
            )

        return (
            existing_task.title == event.summary
            and existing_task.planned_at == event_planned_at
            and existing_task.duration_min == duration_min
            and existing_task.category == "other"
        )

    async def _accumulate_conflict(
        self,
        *,
        task_id: int,
        event: GoogleEventDTO,
        context_status: str,
        duration_min: int,
        category: str,
        summary: GooglePullSummaryDTO,
    ) -> None:
        if context_status not in {"conflict_sleep", "conflict_prayer"}:
            return

        if not await self._should_surface_conflict(task_id=task_id):
            return

        result = await self._get_relevant_conflict_result(
            task_id=task_id,
            start_at=event.start_at,
            duration_min=duration_min,
            category=category,
        )
        if result is None:
            return

        if result.conflict_type == ConflictType.SLEEP:
            summary.conflicts_total += 1
            summary.conflicts_sleep += 1
        elif result.conflict_type == ConflictType.PRAYER:
            summary.conflicts_total += 1
            summary.conflicts_prayer += 1
        else:
            return

        conflict_label = self._format_conflict_label(result.conflict_type)
        start_at_text = (
            event.start_at.astimezone(APP_TZ).strftime("%Y-%m-%d %H:%M")
            if event.start_at is not None
            else "-"
        )
        conflict_message = result.message or "Обнаружен контекстный конфликт."

        summary.notes.append(f"- relevant conflict: {event.summary} ({conflict_label})")

        summary.conflict_items.append(
            GoogleConflictItemDTO(
                task_id=task_id,
                summary=event.summary,
                start_at_text=start_at_text,
                conflict_label=conflict_label,
                conflict_message=conflict_message,
                has_safe_slot=(
                    result.suggested_slot_start is not None
                    and result.suggested_slot_end is not None
                ),
            )
        )

    async def _should_surface_conflict(self, *, task_id: int) -> bool:
        link = await self.link_repo.get_by_task_and_provider(
            task_id=task_id,
            provider="google_calendar",
        )
        if link is None:
            return False

        if link.sync_status not in self.RELEVANT_CONFLICT_SYNC_STATUSES:
            return False

        if not link.external_id:
            return False

        return True

    async def _get_relevant_conflict_result(
        self,
        *,
        task_id: int,
        start_at: datetime | None,
        duration_min: int,
        category: str,
    ):
        if start_at is None:
            return None

        if not await self._should_surface_conflict(task_id=task_id):
            return None

        validator = await self._build_context_validator()
        result = await validator.validate_event(
            start_at=start_at,
            duration_min=duration_min,
            category=category,
            priority_code=None,
        )

        if result.status != ValidationStatus.CONFLICT:
            return None

        if result.conflict_type not in {ConflictType.PRAYER, ConflictType.SLEEP}:
            return None

        return result

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
        )

    @staticmethod
    def _format_conflict_label(conflict_type: ConflictType | None) -> str:
        if conflict_type == ConflictType.PRAYER:
            return "намазом"

        if conflict_type == ConflictType.SLEEP:
            return "сном"

        return "контекстом"
