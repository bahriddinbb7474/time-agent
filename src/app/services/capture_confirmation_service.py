from __future__ import annotations

from dataclasses import dataclass

from app.services.capture_router_service import (
    CAPTURE_KIND_BOSS,
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureDraft,
)


CAPTURE_CALLBACK_PREFIX = "capture"
CAPTURE_ACTION_TASK = "task"
CAPTURE_ACTION_LATER = "later"
CAPTURE_ACTION_BOSS = "boss"
CAPTURE_ACTION_CANCEL = "cancel"


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
