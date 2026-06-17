from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.handlers.add import parse_add_payload
from app.services.crisis_stack_service import CrisisStackService
from app.services.categories import KNOWN_CATEGORIES


CAPTURE_KIND_IGNORE = "ignore"
CAPTURE_KIND_TASK = "task"
CAPTURE_KIND_LATER = "later"
CAPTURE_KIND_BOSS = "boss"

# Texts shorter than this (stripped length) are too short for confident rules classification.
_MIN_MEANINGFUL_LEN = 4

_HELP_PHRASES: tuple[str, ...] = (
    "как пользоваться",
    "что ты умеешь",
    "помоги настроить",
    "какие команды",
    "инструкция",
    "как работает",
    "что умеешь",
    "как работаешь",
    "что можешь",
    "как использовать",
)

_SETTINGS_PHRASES: tuple[str, ...] = (
    "измени цель",
    "добавь цель",
    "добавить цель",
    "установи цель",
    "поменяй цель",
    "настрой сон",
    "настрой цель",
    "отключи ",       # trailing space prevents matching past-tense "отключил"
    "включи напоминание",
    "хочу настроить",
    "хочу изменить цель",
)

# Units that, combined with "хочу", signal a quantity-based goal request.
_SETTINGS_QUANTITY_UNITS: tuple[str, ...] = (
    "литр",
    "стакан",
    "калори",
    "грамм",
)


@dataclass(slots=True, frozen=True)
class CaptureDraft:
    kind: str
    text: str
    category: str | None = None
    title: str | None = None
    planned_at: datetime | None = None
    duration_min: int | None = None
    confidence: float = 1.0
    reason_code: str = "rules"
    needs_clarification: bool = False
    # advisor_intent: "capture" | "help" | "settings" | "unknown"
    advisor_intent: str = "capture"


class CaptureRouterService:
    def classify_text(self, text: str | None) -> CaptureDraft:
        raw = (text or "").strip()
        if not raw:
            return CaptureDraft(kind=CAPTURE_KIND_IGNORE, text="", reason_code="rules_ignore")

        if raw.startswith("/"):
            return CaptureDraft(kind=CAPTURE_KIND_IGNORE, text=raw, reason_code="rules_ignore")

        if len(raw) < _MIN_MEANINGFUL_LEN:
            return CaptureDraft(
                kind=CAPTURE_KIND_LATER,
                text=raw,
                reason_code="rules_unknown",
                advisor_intent="unknown",
                needs_clarification=True,
                confidence=0.4,
            )

        if self._is_help_request(raw):
            return CaptureDraft(
                kind=CAPTURE_KIND_LATER,
                text=raw,
                reason_code="rules_help",
                advisor_intent="help",
                confidence=1.0,
            )

        if self._is_settings_request(raw):
            return CaptureDraft(
                kind=CAPTURE_KIND_LATER,
                text=raw,
                reason_code="rules_settings",
                advisor_intent="settings",
                confidence=1.0,
            )

        category, title, planned_at, duration_min = parse_add_payload(raw)

        if self._is_boss_capture(raw):
            return CaptureDraft(
                kind=CAPTURE_KIND_BOSS,
                text=raw,
                category="work",
                title=title,
                planned_at=planned_at,
                duration_min=duration_min,
                reason_code="rules_boss",
            )

        if planned_at is not None or self._starts_with_known_category(raw):
            return CaptureDraft(
                kind=CAPTURE_KIND_TASK,
                text=raw,
                category=category,
                title=title,
                planned_at=planned_at,
                duration_min=duration_min,
                reason_code="rules_task",
            )

        return CaptureDraft(kind=CAPTURE_KIND_LATER, text=raw, title=raw, reason_code="rules_later")

    @staticmethod
    def _is_help_request(raw: str) -> bool:
        low = raw.lower()
        return any(p in low for p in _HELP_PHRASES)

    @staticmethod
    def _is_settings_request(raw: str) -> bool:
        low = raw.lower()
        if any(p in low for p in _SETTINGS_PHRASES):
            return True
        # "хочу N литра/стаканов/..." — quantity-based goal request
        if "хочу" in low and any(u in low for u in _SETTINGS_QUANTITY_UNITS):
            return True
        return False

    @staticmethod
    def _starts_with_known_category(raw: str) -> bool:
        parts = raw.split(maxsplit=1)
        return bool(parts and parts[0].lower() in KNOWN_CATEGORIES)

    @staticmethod
    def _is_boss_capture(raw: str) -> bool:
        lowered = raw.strip().lower()
        return lowered.startswith(("boss ", "шеф ", "шеф:")) or CrisisStackService.is_urgent_text(raw)
