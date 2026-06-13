"""Crisis Stack service skeleton.

This service is an orchestration layer for crisis-mode task focus:
- stack management
- priority ordering
- focus task handling
- stack rebuild and recovery
- alert switching coordination

Stage 4.7-E / Step 1 provides only structure and method signatures.
Business logic is intentionally not implemented yet.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

log = logging.getLogger("time-agent.crisis_stack")


@dataclass(slots=True)
class CrisisStackItem:
    user_id: int
    task_id: int
    priority_position: int
    stack_status: str
    created_at: datetime


class CrisisStackService:
    """Skeleton service for crisis stack orchestration."""

    CRISIS_URGENT_THRESHOLD = 2

    def activate_crisis_mode(self, user_id: int) -> None:
        log.info("Crisis stack activate signal received for user_id=%s", user_id)

    @staticmethod
    def is_urgent_text(text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        if "🔥" in text:
            return True
        if "рџ”Ґ" in normalized:
            return True
        if normalized.startswith("шеф:"):
            return True
        if normalized.startswith("шеф срочно:"):
            return True
        if "шеф срочно" in normalized:
            return True
        if normalized.startswith("с€рµс„:"):
            return True
        if normalized.startswith("с€рµс„ сѓсрѕс‡рѕ:"):
            return True
        return re.search(r"\bсрочно\b", normalized, flags=re.IGNORECASE) is not None


    @staticmethod
    def _normalize_category(category: str | None) -> str:
        return (category or "").strip().lower()

    @classmethod
    def is_family_a_related(
        cls,
        *,
        title: str,
        category: str | None,
        family_category: str | None = None,
    ) -> bool:
        if cls._normalize_category(category) != "family":
            return False

        normalized_family_category = (family_category or "").strip().upper()
        if normalized_family_category == "A":
            return True

        normalized_title = (title or "").strip().lower()
        family_a_markers = (
            "family:a",
            "family a",
            "семья:a",
            "семья a",
            "inner circle",
            "[a]",
        )
        return any(marker in normalized_title for marker in family_a_markers)

    @classmethod
    def default_urgent_precedence_rank(
        cls,
        *,
        title: str,
        category: str | None,
        family_category: str | None = None,
    ) -> int:
        """
        Narrow compatibility rule for crisis ordering foundation.

        Lower rank means higher default precedence.

        Rule:
        - urgent family A tasks rank above urgent work tasks
        - existing non-urgent tasks are unaffected
        """
        if not cls.is_urgent_text(title):
            return 100

        if cls.is_family_a_related(
            title=title,
            category=category,
            family_category=family_category,
        ):
            return 0

        if cls._normalize_category(category) == "work":
            return 10

        return 20

    @classmethod
    def is_active_task(cls, task) -> bool:
        return getattr(task, "status", None) == "todo"

    @classmethod
    def is_urgent_task(cls, task) -> bool:
        if not cls.is_active_task(task):
            return False

        title = getattr(task, "title", "")
        category = getattr(task, "category", None)
        if cls.is_urgent_text(title):
            return True

        if cls._normalize_category(category) == "work":
            normalized = (title or "").strip().lower()
            return normalized.startswith("шеф:") or "boss" in normalized

        return False

    @classmethod
    def urgent_tasks(cls, tasks: Iterable) -> list:
        return [task for task in tasks if cls.is_urgent_task(task)]

    @classmethod
    def is_crisis(cls, tasks: Iterable) -> bool:
        return len(cls.urgent_tasks(tasks)) >= cls.CRISIS_URGENT_THRESHOLD

    @classmethod
    def select_focus_task(cls, tasks: Sequence):
        active_tasks = [task for task in tasks if cls.is_active_task(task)]
        if not active_tasks:
            return None

        return sorted(active_tasks, key=cls._focus_sort_key)[0]

    @classmethod
    def order_focus_tasks(cls, tasks: Iterable) -> list:
        active_tasks = [task for task in tasks if cls.is_active_task(task)]
        return sorted(active_tasks, key=cls._focus_sort_key)

    @classmethod
    def _focus_sort_key(cls, task) -> tuple:
        planned_at = getattr(task, "planned_at", None)
        planned_rank = 0 if planned_at is not None else 1
        planned_value = planned_at or datetime.max
        return (
            0 if cls.is_urgent_task(task) else 1,
            cls.default_urgent_precedence_rank(
                title=getattr(task, "title", ""),
                category=getattr(task, "category", None),
            ),
            planned_rank,
            planned_value,
            getattr(task, "id", 0),
        )

    def add_task_to_stack(self, user_id: int, task_id: int) -> None:
        raise NotImplementedError

    def insert_task_at_priority(self, user_id: int, task_id: int, position: int) -> None:
        raise NotImplementedError

    def rebuild_stack(self, user_id: int) -> None:
        raise NotImplementedError

    def get_focus_task(self, user_id: int) -> CrisisStackItem | None:
        raise NotImplementedError

    def switch_focus(self, user_id: int) -> CrisisStackItem | None:
        raise NotImplementedError

    def complete_focus_task(self, user_id: int) -> None:
        raise NotImplementedError

    def cancel_task(self, user_id: int, task_id: int) -> None:
        raise NotImplementedError

    def recover_stack(self, user_id: int) -> None:
        raise NotImplementedError
