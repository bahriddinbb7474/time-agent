"""Stage 20.6-A simplified typed free-text boundary."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.capture import TYPED_FREE_TEXT_POLICY, _try_advisor_response
from app.services.capture_router_service import CaptureRouterService
from app.services.checkin_response_classifier import CheckinResponseClassifier


async def main_async() -> None:
    classifier = CheckinResponseClassifier()
    for text, intent in (("всё по плану", "aligned"), ("не помню", "unknown"),
                         ("начал", "started"), ("позже", "defer")):
        assert classifier.classify(text).intent == intent

    normal = CaptureRouterService().classify_text("добавь задачу купить молоко")
    assert normal.kind != "ignore"
    ambiguous = CaptureRouterService().classify_text("что мне сейчас лучше делать")
    provider_call = AsyncMock()
    settings = MagicMock()
    runtime_status = MagicMock(enabled=False, configuration_ready=True)
    with (
        patch("app.handlers.capture.advisor_runtime.status", return_value=runtime_status),
        patch("app.handlers.capture.run_advisor_for_draft", provider_call),
    ):
        handled = await _try_advisor_response(
            MagicMock(), MagicMock(), ambiguous, MagicMock(), settings
        )
    assert handled is False
    provider_call.assert_not_awaited()
    assert TYPED_FREE_TEXT_POLICY == "rules_first_then_existing_capture"


def main() -> None:
    import asyncio
    asyncio.run(main_async())
    print("PASS: typed free text keeps the rules-first/capture boundary")


if __name__ == "__main__":
    main()
