"""Stage 19.9-A owner runtime switch tests. No network or production state."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.handlers.advisor import advisor_off_cmd, advisor_on_cmd, advisor_status_cmd
from app.handlers.capture import _try_advisor_response
from app.services.advisor_runtime_service import AdvisorRuntimeService, advisor_runtime
from app.services.capture_router_service import CaptureRouterService


OWNER_ID = 123456789


def _settings(
    *,
    provider: str = "openrouter",
    key: str = "test-key-not-real",
    request_limit: int = 10,
    cost_limit: float = 0.05,
):
    return SimpleNamespace(
        allowed_telegram_id=OWNER_ID,
        advisor_provider=provider,
        openrouter_api_key=key,
        openrouter_advisor_model="test-model",
        llm_daily_request_limit=request_limit,
        llm_daily_cost_usd_limit=cost_limit,
    )


class _User:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _Chat:
    id = 555


class _Message:
    def __init__(self, user_id: int = OWNER_ID) -> None:
        self.from_user = _User(user_id)
        self.chat = _Chat()
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append(text)


def test_runtime_default_is_off():
    status = AdvisorRuntimeService().status(_settings())
    assert status.enabled is False
    assert status.configuration_ready is True
    assert status.safe is True
    print("PASS: test_runtime_default_is_off")


async def test_status_with_disabled_env_is_safe_and_secret_free():
    advisor_runtime.disable()
    message = _Message()
    settings = _settings(provider="disabled")
    await advisor_status_cmd(message, settings=settings)
    text = message.answers[-1]
    assert "Advisor runtime: disabled" in text
    assert "Provider configured: no" in text
    assert "API key present: yes" in text
    assert "LLM_DAILY_REQUEST_LIMIT: 10" in text
    assert "LLM_DAILY_COST_USD_LIMIT: 0.05" in text
    assert "State: SAFE" in text
    assert "Ready to enable: no" in text
    assert settings.openrouter_api_key not in text
    print("PASS: test_status_with_disabled_env_is_safe_and_secret_free")


async def test_on_blocked_when_env_provider_disabled():
    advisor_runtime.disable()
    message = _Message()
    await advisor_on_cmd(message, settings=_settings(provider="disabled"))
    assert advisor_runtime.status(_settings(provider="disabled")).enabled is False
    assert "provider disabled in env" in message.answers[-1]
    print("PASS: test_on_blocked_when_env_provider_disabled")


async def test_on_blocked_when_limits_are_unsafe():
    for settings, expected in (
        (_settings(request_limit=0), "LLM_DAILY_REQUEST_LIMIT"),
        (_settings(cost_limit=0.0), "LLM_DAILY_COST_USD_LIMIT"),
    ):
        advisor_runtime.disable()
        message = _Message()
        await advisor_on_cmd(message, settings=settings)
        assert advisor_runtime.status(settings).enabled is False
        assert expected in message.answers[-1]
    print("PASS: test_on_blocked_when_limits_are_unsafe")


async def test_on_blocked_when_key_is_missing():
    settings = _settings(key="")
    advisor_runtime.disable()
    message = _Message()
    await advisor_on_cmd(message, settings=settings)
    assert advisor_runtime.status(settings).enabled is False
    assert "OPENROUTER_API_KEY" in message.answers[-1]
    print("PASS: test_on_blocked_when_key_is_missing")


async def test_on_enables_runtime_when_config_is_safe():
    settings = _settings()
    advisor_runtime.disable()
    message = _Message()
    await advisor_on_cmd(message, settings=settings)
    assert advisor_runtime.status(settings).enabled is True
    assert message.answers[-1] == "Advisor runtime: enabled."
    print("PASS: test_on_enables_runtime_when_config_is_safe")


async def test_off_always_sets_runtime_off_for_owner():
    settings = _settings()
    assert advisor_runtime.enable(settings).enabled is True
    message = _Message()
    await advisor_off_cmd(message, settings=settings)
    assert advisor_runtime.status(settings).enabled is False
    assert message.answers[-1] == "Advisor runtime: disabled."
    print("PASS: test_off_always_sets_runtime_off_for_owner")


async def test_unauthorized_user_cannot_toggle_runtime():
    settings = _settings()
    advisor_runtime.disable()
    message = _Message(user_id=OWNER_ID + 1)
    await advisor_on_cmd(message, settings=settings)
    assert advisor_runtime.status(settings).enabled is False
    assert message.answers == []
    print("PASS: test_unauthorized_user_cannot_toggle_runtime")


async def test_capture_skips_advisor_when_runtime_off():
    settings = _settings()
    advisor_runtime.disable()
    message = _Message()
    draft = CaptureRouterService().classify_text("как пользоваться ботом")
    provider_call = AsyncMock()
    with patch("app.handlers.capture.run_advisor_for_draft", provider_call):
        handled = await _try_advisor_response(
            message,
            MagicMock(),
            draft,
            MagicMock(),
            settings,
        )
    assert handled is False
    provider_call.assert_not_awaited()
    print("PASS: test_capture_skips_advisor_when_runtime_off")


async def test_capture_allows_advisor_when_runtime_on_and_config_safe():
    settings = _settings()
    assert advisor_runtime.enable(settings).enabled is True
    message = _Message()
    draft = CaptureRouterService().classify_text("как пользоваться ботом")
    orchestration = object()
    provider_call = AsyncMock(return_value=orchestration)
    presentation = SimpleNamespace(
        safe_to_show=True,
        requires_confirmation=False,
        text="Advisor help",
    )
    try:
        with (
            patch("app.handlers.capture.run_advisor_for_draft", provider_call),
            patch("app.handlers.capture.format_advisor_result", return_value=presentation),
        ):
            handled = await _try_advisor_response(
                message,
                MagicMock(),
                draft,
                MagicMock(),
                settings,
            )
        assert handled is True
        provider_call.assert_awaited_once()
        assert message.answers == ["Advisor help"]
    finally:
        advisor_runtime.disable()
    print("PASS: test_capture_allows_advisor_when_runtime_on_and_config_safe")


async def test_advisor_on_cmd_state_visible_to_capture_path():
    """Verify /advisor_on command state is the same instance seen by _try_advisor_response."""
    settings = _settings()
    advisor_runtime.disable()

    # Owner sends /advisor_on
    cmd_msg = _Message()
    await advisor_on_cmd(cmd_msg, settings=settings)
    assert advisor_runtime.status(settings).enabled is True
    assert cmd_msg.answers[-1] == "Advisor runtime: enabled."

    # Capture path must see the updated state without restart
    draft = CaptureRouterService().classify_text("как пользоваться ботом")
    capture_msg = _Message()
    provider_call = AsyncMock(return_value=MagicMock())
    presentation = SimpleNamespace(safe_to_show=True, requires_confirmation=False, text="AI help")
    try:
        with (
            patch("app.handlers.capture.run_advisor_for_draft", provider_call),
            patch("app.handlers.capture.format_advisor_result", return_value=presentation),
        ):
            handled = await _try_advisor_response(
                capture_msg, MagicMock(), draft, MagicMock(), settings,
            )
        assert handled is True, "capture path must use advisor when runtime is ON"
        provider_call.assert_awaited_once()
        assert capture_msg.answers == ["AI help"]
    finally:
        advisor_runtime.disable()
    print("PASS: test_advisor_on_cmd_state_visible_to_capture_path")


async def test_advisor_off_cmd_stops_capture_path():
    """Verify /advisor_off command is immediately visible to _try_advisor_response."""
    settings = _settings()
    advisor_runtime.enable(settings)

    # Owner sends /advisor_off
    cmd_msg = _Message()
    await advisor_off_cmd(cmd_msg, settings=settings)
    assert advisor_runtime.status(settings).enabled is False

    # Capture path must now skip advisor
    draft = CaptureRouterService().classify_text("как пользоваться ботом")
    provider_call = AsyncMock()
    with patch("app.handlers.capture.run_advisor_for_draft", provider_call):
        handled = await _try_advisor_response(
            _Message(), MagicMock(), draft, MagicMock(), settings,
        )
    assert handled is False, "capture path must skip advisor when runtime is OFF"
    provider_call.assert_not_awaited()
    print("PASS: test_advisor_off_cmd_stops_capture_path")


SYNC_TESTS = [test_runtime_default_is_off]
ASYNC_TESTS = [
    test_status_with_disabled_env_is_safe_and_secret_free,
    test_on_blocked_when_env_provider_disabled,
    test_on_blocked_when_limits_are_unsafe,
    test_on_blocked_when_key_is_missing,
    test_on_enables_runtime_when_config_is_safe,
    test_off_always_sets_runtime_off_for_owner,
    test_unauthorized_user_cannot_toggle_runtime,
    test_capture_skips_advisor_when_runtime_off,
    test_capture_allows_advisor_when_runtime_on_and_config_safe,
    test_advisor_on_cmd_state_visible_to_capture_path,
    test_advisor_off_cmd_stops_capture_path,
]


async def main_async() -> None:
    for test in ASYNC_TESTS:
        await test()


def main() -> None:
    for test in SYNC_TESTS:
        test()
    asyncio.run(main_async())
    print(f"\nALL {len(SYNC_TESTS) + len(ASYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
