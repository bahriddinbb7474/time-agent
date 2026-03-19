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

    def activate_crisis_mode(self, user_id: int) -> None:
        log.info("Crisis stack activate signal received for user_id=%s", user_id)

    @staticmethod
    def is_urgent_text(text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        if "🔥" in text:
            return True
        if "шеф срочно" in normalized:
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
