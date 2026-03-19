from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
from typing import Awaitable, Callable, Iterable

from app.core.time import APP_TZ
from app.db import crud
from app.services.daily_context_service import DailyContextPolicy, DailyContextService
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService
from app.services.rules_service import RulesService
from app.services.validation_result import (
    ConflictType,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)


log = logging.getLogger("time-agent.context_validator")


@dataclass(slots=True)
class ConflictWindow:
    conflict_type: ConflictType
    reason_code: str
    message: str
    severity: ValidationSeverity
    start: datetime
    end: datetime


class ContextValidator:
    """
    Pure validation service.

    Important:
    - does NOT write to DB
    - does NOT create/update tasks
    - only returns ValidationResult
    """

    CHECKPOINT_STEP_MIN = 15
    SEARCH_STEP_MIN = 15
    SEARCH_LIMIT_HOURS = 24

    PRAYER_BUFFER_BEFORE_MIN = 15
    PRAYER_BLOCK_AFTER_MIN = 20
    SUGGESTION_BUFFER_MIN = 15
    PRAYER_SUGGESTION_BUFFER_MIN = 20

    DHUHR_DEAD_ZONE_START = time(13, 0)
    DHUHR_DEAD_ZONE_END = time(13, 20)
    DHUHR_DEAD_ZONE_SHIFT_TO = time(13, 25)

    SIYAM_HEAVY_CATEGORIES = {"health", "workout", "heavy_activity"}

    def __init__(
        self,
        routine_service: RoutineService,
        prayer_times_service: PrayerTimesService,
        rules_service: RulesService,
        daily_context_service: DailyContextService | None = None,
    ) -> None:
        self.routine_service = routine_service
        self.prayer_times_service = prayer_times_service
        self.rules_service = rules_service
        self.daily_context_service = daily_context_service

    async def validate_event(
        self,
        *,
        start_at: datetime | None,
        duration_min: int,
        category: str | None = None,
        priority_code: str | None = None,
        include_suggestion: bool = True,
    ) -> ValidationResult:
        """
        Stage 4.7-C validation flow:
        1. floating tasks -> VALID
        2. sleep / second sleep check
        3. prayer check
        4. protected/family slots check
        5. siyam daytime heavy-load check
        6. build recursively revalidated suggested safe slot for conflicts
        """
        if start_at is None:
            return ValidationResult(
                status=ValidationStatus.VALID,
                severity=ValidationSeverity.INFO,
                reason_code="floating_task",
                message="Floating task has no context conflict.",
            )

        local_start = self._ensure_app_tz(start_at)
        local_end = local_start + timedelta(minutes=duration_min)

        sleep_conflict = await self._detect_sleep_conflict(
            start_at=local_start,
            end_at=local_end,
            priority_code=priority_code,
        )
        if sleep_conflict is not None:
            return await self._build_conflict_result(
                conflict=sleep_conflict,
                duration_min=duration_min,
                category=category,
                priority_code=priority_code,
                include_suggestion=include_suggestion,
            )

        prayer_conflict = await self._detect_prayer_conflict(
            start_at=local_start,
            end_at=local_end,
        )
        if prayer_conflict is not None:
            return await self._build_conflict_result(
                conflict=prayer_conflict,
                duration_min=duration_min,
                category=category,
                priority_code=priority_code,
                include_suggestion=include_suggestion,
            )

        protected_conflict = await self._detect_protected_slot_conflict(
            start_at=local_start,
            end_at=local_end,
        )
        if protected_conflict is not None:
            return await self._build_conflict_result(
                conflict=protected_conflict,
                duration_min=duration_min,
                category=category,
                priority_code=priority_code,
                include_suggestion=include_suggestion,
            )

        siyam_conflict = await self._detect_siyam_conflict(
            start_at=local_start,
            end_at=local_end,
            category=category,
        )
        if siyam_conflict is not None:
            return await self._build_conflict_result(
                conflict=siyam_conflict,
                duration_min=duration_min,
                category=category,
                priority_code=priority_code,
                include_suggestion=include_suggestion,
            )

        return ValidationResult(
            status=ValidationStatus.VALID,
            severity=ValidationSeverity.INFO,
            reason_code="ok",
            message="Event passed context validation.",
        )

    async def _build_conflict_result(
        self,
        *,
        conflict: ConflictWindow,
        duration_min: int,
        category: str | None,
        priority_code: str | None,
        include_suggestion: bool,
    ) -> ValidationResult:
        suggested_start: datetime | None = None
        suggested_end: datetime | None = None

        if include_suggestion:
            if conflict.reason_code == "dhuhr_dead_zone":
                suggested_start = self._build_dhuhr_dead_zone_shift_start(
                    day=conflict.start.date(),
                )
                suggested_end = suggested_start + timedelta(minutes=duration_min)
            else:
                buffer_min = self._suggestion_buffer_for_conflict(conflict)
                start_after = conflict.end + timedelta(minutes=buffer_min)
                suggested_start, suggested_end = await self._find_next_safe_slot(
                    start_after=start_after,
                    duration_min=duration_min,
                    category=category,
                    priority_code=priority_code,
                )

        message = conflict.message
        if suggested_start is not None and suggested_end is not None:
            slot_text = (
                f"{suggested_start.strftime('%H:%M')}–{suggested_end.strftime('%H:%M')}"
            )
            message = f"{conflict.message} Ближайшее свободное окно: {slot_text}."

        return ValidationResult(
            status=ValidationStatus.CONFLICT,
            severity=conflict.severity,
            reason_code=conflict.reason_code,
            message=message,
            conflict_type=conflict.conflict_type,
            conflict_start=conflict.start,
            conflict_end=conflict.end,
            recommended_action=(
                "dhuhr_dead_zone_shift"
                if conflict.reason_code == "dhuhr_dead_zone"
                else "shift_after_prayer"
                if conflict.conflict_type == ConflictType.PRAYER
                else None
            ),
            suggested_slot_start=suggested_start,
            suggested_slot_end=suggested_end,
        )

    async def _detect_sleep_conflict(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        priority_code: str | None,
    ) -> ConflictWindow | None:
        """
        Sleep policy:
        - second sleep overlap => only BOSS_CRITICAL allowed
        - primary sleep overlap => hard block
        """
        checkpoints = self._build_checkpoints(start_at, end_at)

        first_primary_point: datetime | None = None
        first_second_point: datetime | None = None

        for point in checkpoints:
            if await self.routine_service.is_second_sleep(point):
                if first_second_point is None:
                    first_second_point = point

            if await self.routine_service.is_sleep_time(point):
                if first_primary_point is None:
                    first_primary_point = point

        if first_second_point is not None:
            if priority_code == "BOSS_CRITICAL":
                return None

            conflict_end = await self._find_window_end(
                probe_from=first_second_point,
                predicate=self.routine_service.is_second_sleep,
                fallback_end=end_at,
            )
            return ConflictWindow(
                conflict_type=ConflictType.SECOND_SLEEP,
                reason_code="second_sleep_conflict",
                message="Событие попадает во второе окно сна.",
                severity=ValidationSeverity.HARD_BLOCK,
                start=first_second_point,
                end=conflict_end,
            )

        if first_primary_point is not None:
            conflict_end = await self._find_window_end(
                probe_from=first_primary_point,
                predicate=self.routine_service.is_sleep_time,
                fallback_end=end_at,
            )
            return ConflictWindow(
                conflict_type=ConflictType.SLEEP,
                reason_code="sleep_conflict",
                message="Событие попадает в окно сна.",
                severity=ValidationSeverity.HARD_BLOCK,
                start=first_primary_point,
                end=conflict_end,
            )

        return None

    async def _detect_prayer_conflict(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> ConflictWindow | None:
        """
        Prayer policy:
        protected zone starts 15 min before prayer
        and lasts 20 min after prayer start.
        """
        for day in self._iter_dates(start_at.date(), end_at.date()):
            prayer_times = await self.prayer_times_service.get_prayer_times(day)

            prayer_points = [
                ("Fajr", prayer_times.fajr),
                ("Dhuhr", prayer_times.dhuhr),
                ("Asr", prayer_times.asr),
                ("Maghrib", prayer_times.maghrib),
                ("Isha", prayer_times.isha),
            ]

            for prayer_name, prayer_time in prayer_points:
                prayer_at = datetime.combine(day, prayer_time, tzinfo=APP_TZ)
                protected_start = prayer_at - timedelta(
                    minutes=self.PRAYER_BUFFER_BEFORE_MIN
                )
                protected_end = prayer_at + timedelta(
                    minutes=self.PRAYER_BLOCK_AFTER_MIN
                )

                if prayer_name.lower() == "dhuhr" and self._is_dhuhr_dead_zone_overlap(
                    start_at=start_at,
                    end_at=end_at,
                    day=day,
                ):
                    dead_zone_start = datetime.combine(
                        day,
                        self.DHUHR_DEAD_ZONE_START,
                        tzinfo=APP_TZ,
                    )
                    dead_zone_end = datetime.combine(
                        day,
                        self.DHUHR_DEAD_ZONE_END,
                        tzinfo=APP_TZ,
                    )
                    return ConflictWindow(
                        conflict_type=ConflictType.PRAYER,
                        reason_code="dhuhr_dead_zone",
                        message="С 13:00 до 13:20 время Зухра.",
                        severity=ValidationSeverity.WARNING,
                        start=dead_zone_start,
                        end=dead_zone_end,
                    )

                if self._intervals_overlap(
                    start_at,
                    end_at,
                    protected_start,
                    protected_end,
                ):
                    if await self._is_prayer_slot_completed(
                        day=day,
                        prayer_name=prayer_name,
                    ):
                        continue

                    return ConflictWindow(
                        conflict_type=ConflictType.PRAYER,
                        reason_code="prayer_conflict",
                        message=f"В это время намаз {prayer_name}.",
                        severity=ValidationSeverity.WARNING,
                        start=protected_start,
                        end=protected_end,
                    )

        return None

    def _is_dhuhr_dead_zone_overlap(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        day: date,
    ) -> bool:
        dead_zone_start = datetime.combine(
            day,
            self.DHUHR_DEAD_ZONE_START,
            tzinfo=APP_TZ,
        )
        dead_zone_end = datetime.combine(
            day,
            self.DHUHR_DEAD_ZONE_END,
            tzinfo=APP_TZ,
        )
        return self._intervals_overlap(start_at, end_at, dead_zone_start, dead_zone_end)

    def _build_dhuhr_dead_zone_shift_start(self, *, day: date) -> datetime:
        return datetime.combine(day, self.DHUHR_DEAD_ZONE_SHIFT_TO, tzinfo=APP_TZ)

    async def _is_prayer_slot_completed(
        self,
        *,
        day: date,
        prayer_name: str,
    ) -> bool:
        entity_id = f"{day.isoformat()}:{prayer_name.lower()}"
        alert = await crud.get_latest_alert_by_entity(
            self.prayer_times_service.session,
            alert_type="prayer_reminder",
            entity_type="prayer",
            entity_id=entity_id,
        )
        return alert is not None and alert.status == "done"

    async def _detect_protected_slot_conflict(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> ConflictWindow | None:
        duration_min = max(
            1,
            int((end_at - start_at).total_seconds() // 60),
        )

        conflicts = await self.rules_service.check_conflicts(
            planned_at=start_at,
            duration_min=duration_min,
        )
        if not conflicts:
            return None

        first_rule = conflicts[0]
        window_start, window_end = self._resolve_rule_window_for_datetime(
            rule=first_rule,
            probe_dt=start_at,
        )

        return ConflictWindow(
            conflict_type=ConflictType.FAMILY,
            reason_code="protected_slot_conflict",
            message=f"Событие попадает в защищённый слот: {first_rule.name}.",
            severity=ValidationSeverity.HARD_BLOCK,
            start=window_start,
            end=window_end,
        )

    async def _detect_siyam_conflict(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        category: str | None,
    ) -> ConflictWindow | None:
        """
        Siyam-first foundation logic:
        - uses persisted daily context when available
        - falls back to existing Monday/Thursday heuristic
        - returns soft warning only
        """
        if not category or category.lower() not in self.SIYAM_HEAVY_CATEGORIES:
            return None

        policy = await self._resolve_daily_siyam_policy(start_at.date())
        if not policy.is_siyam_day:
            return None

        prayer_times = await self.prayer_times_service.get_prayer_times(start_at.date())
        fasting_start = datetime.combine(
            start_at.date(),
            prayer_times.fajr,
            tzinfo=APP_TZ,
        )
        fasting_end = datetime.combine(
            start_at.date(),
            prayer_times.maghrib,
            tzinfo=APP_TZ,
        )

        if self._intervals_overlap(start_at, end_at, fasting_start, fasting_end):
            message = (
                "Тяжёлая нагрузка попадает на дневное окно поста "
                "(Siyam daytime load)."
            )

            second_half_start = fasting_start + (fasting_end - fasting_start) / 2
            if policy.low_energy_mode and start_at >= second_half_start:
                message = (
                    f"{message} "
                    "Режим низкой энергии активен: во второй половине дня "
                    "рекомендуется снизить интенсивность."
                )

            return ConflictWindow(
                conflict_type=ConflictType.SIYAM_DAYTIME_LOAD,
                reason_code="siyam_daytime_load",
                message=message,
                severity=ValidationSeverity.WARNING,
                start=max(start_at, fasting_start),
                end=fasting_end,
            )

        return None

    async def _resolve_daily_siyam_policy(self, target_date: date) -> DailyContextPolicy:
        default_is_siyam = target_date.weekday() in (0, 3)
        fallback_policy = DailyContextPolicy(
            date=target_date,
            is_siyam_day=default_is_siyam,
            hydration_daylight_suppressed=default_is_siyam,
            low_energy_mode=False,
            siyam_state_source=DailyContextService.SIYAM_SOURCE_HEURISTIC,
        )

        service = self.daily_context_service
        if service is None:
            log.debug(
                "Siyam policy fallback: daily_context_service is not configured date=%s",
                target_date.isoformat(),
            )
            return fallback_policy

        try:
            policy = await service.get_policy_for_date(target_date)
            if policy is None:
                return fallback_policy
            return policy
        except Exception:
            log.exception(
                "Siyam policy fallback: failed to read daily context date=%s",
                target_date.isoformat(),
            )
            return fallback_policy

    async def _find_next_safe_slot(
        self,
        *,
        start_after: datetime,
        duration_min: int,
        category: str | None,
        priority_code: str | None,
    ) -> tuple[datetime | None, datetime | None]:
        candidate_start = self._round_up_to_step(
            self._ensure_app_tz(start_after),
            step_min=self.SEARCH_STEP_MIN,
        )
        deadline = candidate_start + timedelta(hours=self.SEARCH_LIMIT_HOURS)

        while candidate_start <= deadline:
            candidate_end = candidate_start + timedelta(minutes=duration_min)

            result = await self.validate_event(
                start_at=candidate_start,
                duration_min=duration_min,
                category=category,
                priority_code=priority_code,
                include_suggestion=False,
            )

            if result.status == ValidationStatus.VALID:
                return candidate_start, candidate_end

            next_probe_from = self._choose_next_probe_start(
                current_start=candidate_start,
                validation_result=result,
            )
            candidate_start = self._round_up_to_step(
                next_probe_from,
                step_min=self.SEARCH_STEP_MIN,
            )

        return None, None

    def _suggestion_buffer_for_conflict(self, conflict: ConflictWindow) -> int:
        if conflict.conflict_type == ConflictType.PRAYER:
            return self.PRAYER_SUGGESTION_BUFFER_MIN
        return self.SUGGESTION_BUFFER_MIN

    def _choose_next_probe_start(
        self,
        *,
        current_start: datetime,
        validation_result: ValidationResult,
    ) -> datetime:
        if validation_result.conflict_end is not None:
            return validation_result.conflict_end + timedelta(
                minutes=self.SUGGESTION_BUFFER_MIN
            )

        return current_start + timedelta(minutes=self.SEARCH_STEP_MIN)

    async def _find_window_end(
        self,
        *,
        probe_from: datetime,
        predicate: Callable[[datetime], Awaitable[bool]],
        fallback_end: datetime,
    ) -> datetime:
        current = self._ensure_app_tz(probe_from)
        max_probe = current + timedelta(hours=12)

        while current <= max_probe:
            if not await predicate(current):
                return current
            current += timedelta(minutes=self.CHECKPOINT_STEP_MIN)

        return fallback_end

    def _resolve_rule_window_for_datetime(
        self,
        *,
        rule,
        probe_dt: datetime,
    ) -> tuple[datetime, datetime]:
        start_time_obj = datetime.strptime(rule.start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(rule.end_time, "%H:%M").time()

        local_probe = self._ensure_app_tz(probe_dt)
        day = local_probe.date()
        prev_day = day - timedelta(days=1)
        next_day = day + timedelta(days=1)

        if end_time_obj > start_time_obj:
            start_dt = datetime.combine(day, start_time_obj, tzinfo=APP_TZ)
            end_dt = datetime.combine(day, end_time_obj, tzinfo=APP_TZ)
            return start_dt, end_dt

        prev_start = datetime.combine(prev_day, start_time_obj, tzinfo=APP_TZ)
        prev_end = datetime.combine(day, end_time_obj, tzinfo=APP_TZ)

        if prev_start <= local_probe < prev_end:
            return prev_start, prev_end

        curr_start = datetime.combine(day, start_time_obj, tzinfo=APP_TZ)
        curr_end = datetime.combine(next_day, end_time_obj, tzinfo=APP_TZ)
        return curr_start, curr_end

    @staticmethod
    def _ensure_app_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)

    @staticmethod
    def _build_checkpoints(start_at: datetime, end_at: datetime) -> list[datetime]:
        """
        Builds checkpoints across the event interval.
        """
        if end_at <= start_at:
            return [start_at]

        checkpoints = [start_at]
        current = start_at

        while current < end_at:
            current = current + timedelta(minutes=15)
            if current < end_at:
                checkpoints.append(current)

        checkpoints.append(end_at - timedelta(seconds=1))
        return checkpoints

    @staticmethod
    def _intervals_overlap(
        start_a: datetime,
        end_a: datetime,
        start_b: datetime,
        end_b: datetime,
    ) -> bool:
        return start_a < end_b and start_b < end_a

    @staticmethod
    def _iter_dates(start_date: date, end_date: date) -> Iterable[date]:
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)

    @staticmethod
    def _round_up_to_step(dt: datetime, *, step_min: int) -> datetime:
        dt = dt.replace(second=0, microsecond=0)

        remainder = dt.minute % step_min
        if remainder == 0:
            return dt

        delta = step_min - remainder
        return dt + timedelta(minutes=delta)





