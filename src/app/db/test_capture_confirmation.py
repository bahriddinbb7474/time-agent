from app.services.capture_confirmation_service import (
    CAPTURE_ACTION_BOSS,
    CAPTURE_ACTION_CANCEL,
    CAPTURE_ACTION_EXPIRED_CANCEL,
    CAPTURE_ACTION_EXPIRED_LATER,
    CAPTURE_ACTION_LATER,
    CAPTURE_ACTION_TASK,
    build_capture_button_specs,
    build_capture_callback_data,
    build_capture_confirmation_text,
    build_expired_capture_button_specs,
    build_expired_capture_text,
)
from app.services.capture_router_service import (
    CAPTURE_KIND_LATER,
    CaptureDraft,
)


def main():
    draft = CaptureDraft(
        kind=CAPTURE_KIND_LATER,
        text="Записать идею для проекта",
    )
    text = build_capture_confirmation_text(draft)
    assert "Записать идею для проекта" in text
    assert "Как сохранить?" in text

    buttons = build_capture_button_specs()
    assert [button.text for button in buttons] == [
        "Создать задачу",
        "На потом",
        "Boss",
        "Отмена",
    ]
    assert [button.callback_data for button in buttons] == [
        build_capture_callback_data(CAPTURE_ACTION_TASK),
        build_capture_callback_data(CAPTURE_ACTION_LATER),
        build_capture_callback_data(CAPTURE_ACTION_BOSS),
        build_capture_callback_data(CAPTURE_ACTION_CANCEL),
    ]
    assert all(len(button.callback_data) <= 64 for button in buttons)

    expired_text = build_expired_capture_text(draft)
    assert draft.text in expired_text

    expired_buttons = build_expired_capture_button_specs()
    assert [button.callback_data for button in expired_buttons] == [
        build_capture_callback_data(CAPTURE_ACTION_EXPIRED_LATER),
        build_capture_callback_data(CAPTURE_ACTION_EXPIRED_CANCEL),
    ]
    assert all(len(button.callback_data) <= 64 for button in expired_buttons)

    print("PASS: capture confirmation helpers are pure and short")


if __name__ == "__main__":
    main()
