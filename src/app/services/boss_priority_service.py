from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db import crud
from app.db.models import AlertQueue
from app.services.prayer_times_service import PrayerTimesService
from app.services.routine_service import RoutineService


@dataclass(slots=True)
class BossPriorityDecision:
    is_boss_task: bool
    is_critical: bool
    should_wake_now: bool
    delayed_until: datetime | None
    repeat_interval_min: int | None
    urgency_code: str
    message: str


class BossPriorityService:
    """
    Boss priority evaluator for Stage 4.7-B / 4.7-C / 4.7-D step 1.
    """

    DEFAULT_REPEAT_MIN = 15
    DEFAULT_MAX_REPEATS = 20

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.prayer_times_service = PrayerTimesService(session)
        self.routine_service = RoutineService(
            session=session,
            prayer_times_service=self.prayer_times_service,
        )

    async def evaluate_task(
        self,
        *,
        title: str,
        now_dt: datetime | None = None,
        deadline_at: datetime | None = None,
    ) -> BossPriorityDecision:
        now_local = self._ensure_app_tz(now_dt or datetime.now(APP_TZ))

        is_boss_task = self._is_boss_task(title)
        is_critical = self._is_explicit_critical(title)

        if not is_boss_task:
            return BossPriorityDecision(
                is_boss_task=False,
                is_critical=False,
                should_wake_now=False,
                delayed_until=None,
                repeat_interval_min=None,
                urgency_code="normal",
                message="Not a boss-priority task.",
            )

        in_sleep = await self.routine_service.is_sleep_time(now_local)
        in_second_sleep = await self.routine_service.is_second_sleep(now_local)
        in_any_sleep = in_sleep or in_second_sleep

        urgency_code = self._compute_urgency(
            now_dt=now_local,
            deadline_at=deadline_at,
            is_critical=is_critical,
        )

        if in_any_sleep and not is_critical:
            wake_slot = await self.find_next_wake_slot(now_local)
            return BossPriorityDecision(
                is_boss_task=True,
                is_critical=False,
                should_wake_now=False,
                delayed_until=wake_slot,
                repeat_interval_min=self.DEFAULT_REPEAT_MIN,
                urgency_code=urgency_code,
                message=(
                    "Boss task detected during sleep window. "
                    "No explicit 🔥 marker, so wake-up is postponed."
                ),
            )

        return BossPriorityDecision(
            is_boss_task=True,
            is_critical=is_critical,
            should_wake_now=True,
            delayed_until=None,
            repeat_interval_min=self.DEFAULT_REPEAT_MIN,
            urgency_code=urgency_code,
            message=(
                "Critical boss task requires immediate alert."
                if is_critical
                else "Boss task may alert now because user is awake."
            ),
        )

    async def create_or_update_alert(
        self,
        *,
        chat_id: int,
        task_id: int | str,
        title: str,
        deadline_at: datetime | None = None,
        now_dt: datetime | None = None,
    ) -> AlertQueue | None:
        decision = await self.evaluate_task(
            title=title,
            now_dt=now_dt,
            deadline_at=deadline_at,
        )

        if not decision.is_boss_task:
            return None

        now_local = self._ensure_app_tz(now_dt or datetime.now(APP_TZ))
        scheduled_for = decision.delayed_until or now_local

        payload = {
            "chat_id": chat_id,
            "task_id": task_id,
            "text": self._build_alert_text(
                title=title,
                deadline_at=deadline_at,
                urgency_code=decision.urgency_code,
                is_critical=decision.is_critical,
            ),
            "repeat_count": 0,
            "max_repeats": self.DEFAULT_MAX_REPEATS,
            "deadline_at": deadline_at.isoformat() if deadline_at else None,
            "urgency_code": decision.urgency_code,
            "boss_title": title,
            "critical": decision.is_critical,
        }

        return await crud.create_or_reuse_alert(
            self.session,
            alert_type="boss_critical",
            entity_type="task",
            entity_id=str(task_id),
            scheduled_for=scheduled_for,
            repeat_interval_min=decision.repeat_interval_min,
            priority=self._priority_from_decision(decision),
            payload_json=json.dumps(payload, ensure_ascii=False),
            status="pending",
        )

    async def close_active_alert_for_task(
        self,
        *,
        task_id: int | str,
        reason: str = "boss_marker_removed",
    ) -> bool:
        existing = await crud.get_active_alert_by_key(
            self.session,
            alert_type="boss_critical",
            entity_type="task",
            entity_id=str(task_id),
        )
        if existing is None:
            return False

        now_local = datetime.now(APP_TZ)
        payload = self._load_payload(existing.payload_json)
        payload["stopped_reason"] = reason

        existing.status = "cancelled"
        existing.completed_at = now_local
        existing.updated_at = now_local
        existing.payload_json = json.dumps(payload, ensure_ascii=False)

        await self.session.commit()
        return True

    async def find_next_wake_slot(self, start_at: datetime) -> datetime | None:
        probe = self._ensure_app_tz(start_at).replace(second=0, microsecond=0)
        limit = probe + timedelta(hours=12)

        while probe <= limit:
            in_sleep = await self.routine_service.is_sleep_time(probe)
            in_second_sleep = await self.routine_service.is_second_sleep(probe)

            if not in_sleep and not in_second_sleep:
                return probe

            probe += timedelta(minutes=15)

        return None

    def _build_alert_text(
        self,
        *,
        title: str,
        deadline_at: datetime | None,
        urgency_code: str,
        is_critical: bool,
    ) -> str:
        prefix = "🔥 Шеф: критическая задача" if is_critical else "💼 Шеф: задача"
        parts = [prefix, title]

        if deadline_at is not None:
            local_deadline = self._ensure_app_tz(deadline_at)
            parts.append(f"Deadline: {local_deadline.strftime('%Y-%m-%d %H:%M')}")

        parts.append(f"Urgency: {urgency_code}")
        parts.append("Подтвердите выполнение после закрытия задачи.")
        return "\n".join(parts)

    def _compute_urgency(
        self,
        *,
        now_dt: datetime,
        deadline_at: datetime | None,
        is_critical: bool,
    ) -> str:
        if is_critical:
            return "critical"

        if deadline_at is None:
            return "high"

        deadline_local = self._ensure_app_tz(deadline_at)
        delta = deadline_local - now_dt

        if delta <= timedelta(minutes=30):
            return "critical"
        if delta <= timedelta(hours=2):
            return "high"
        return "normal"

    def _priority_from_decision(self, decision: BossPriorityDecision) -> int:
        if decision.is_critical:
            return 1000
        if decision.urgency_code == "high":
            return 900
        return 800

    @staticmethod
    def _is_boss_task(title: str) -> bool:
        lowered = title.lower()
        return "🔥" in title or lowered.startswith("шеф срочно:")

    @staticmethod
    def _is_explicit_critical(title: str) -> bool:
        return "🔥" in title

    @staticmethod
    def _ensure_app_tz(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)

    @staticmethod
    def _load_payload(payload_json: str | None) -> dict:
        if not payload_json:
            return {}

        try:
            data = json.loads(payload_json)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}

        return {}
