from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.capture_router_service import (
    CAPTURE_KIND_BOSS,
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureDraft,
)

if TYPE_CHECKING:
    from app.services.advisor_presentation_service import AdvisorPresentationResult


CAPTURE_CALLBACK_PREFIX = "capture"
CAPTURE_ACTION_TASK = "task"
CAPTURE_ACTION_LATER = "later"
CAPTURE_ACTION_BOSS = "boss"
CAPTURE_ACTION_CANCEL = "cancel"
CAPTURE_ACTION_EXPIRED_LATER = "expired_later"
CAPTURE_ACTION_EXPIRED_CANCEL = "expired_cancel"

ADVISOR_CAPTURE_CALLBACK_PREFIX = "advisor_capture"

_ADVISOR_ACTION_LABELS: dict[str, str] = {
    "confirm_task": "Создать задачу (AI)",
    "confirm_later": "На потом (AI)",
    "confirm_boss": "Boss (AI)",
    "confirm_activity": "Подтвердить активность (AI)",
    "confirm_settings_change": "Применить (AI)",
    "ask_clarification": "Уточнить",
    "cancel": "Отмена",
}


@dataclass(slots=True, frozen=True)
class CaptureButtonSpec:
    text: str
    callback_data: str


def build_capture_callback_data(action: str) -> str:
    return f"{CAPTURE_CALLBACK_PREFIX}:{action}"


def build_capture_confirmation_text(draft: CaptureDraft) -> str:
    label = {
        CAPTURE_KIND_TASK: "Похоже на задачу.",
        CAPTURE_KIND_LATER: "Похоже на мысль на потом.",
        CAPTURE_KIND_BOSS: "Похоже на срочную задачу.",
    }.get(draft.kind, "Поймал.")

    text = draft.text.strip()
    if len(text) > 120:
        text = f"{text[:117]}..."

    return f"{label}\n{text}\nКак сохранить?"


def build_capture_button_specs() -> list[CaptureButtonSpec]:
    return [
        CaptureButtonSpec(
            text="Создать задачу",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_TASK),
        ),
        CaptureButtonSpec(
            text="На потом",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_LATER),
        ),
        CaptureButtonSpec(
            text="Boss",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_BOSS),
        ),
        CaptureButtonSpec(
            text="Отмена",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_CANCEL),
        ),
    ]


def build_expired_capture_text(draft: CaptureDraft) -> str:
    text = draft.text.strip()
    if len(text) > 120:
        text = f"{text[:117]}..."

    return f"Есть старый черновик.\n{text}\nЧто сделать?"


def build_expired_capture_button_specs() -> list[CaptureButtonSpec]:
    return [
        CaptureButtonSpec(
            text="На потом",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_EXPIRED_LATER),
        ),
        CaptureButtonSpec(
            text="Отмена",
            callback_data=build_capture_callback_data(CAPTURE_ACTION_EXPIRED_CANCEL),
        ),
    ]


def build_advisor_callback_data(action: str) -> str:
    return f"{ADVISOR_CAPTURE_CALLBACK_PREFIX}:{action}"


def build_advisor_button_specs(
    presentation: "AdvisorPresentationResult",
) -> list[CaptureButtonSpec]:
    specs: list[CaptureButtonSpec] = []
    if presentation.primary_action:
        label = _ADVISOR_ACTION_LABELS.get(presentation.primary_action, presentation.primary_action)
        specs.append(CaptureButtonSpec(
            text=label,
            callback_data=build_advisor_callback_data(presentation.primary_action),
        ))
    for action in presentation.secondary_actions:
        label = _ADVISOR_ACTION_LABELS.get(action, action)
        specs.append(CaptureButtonSpec(
            text=label,
            callback_data=build_advisor_callback_data(action),
        ))
    return specs
