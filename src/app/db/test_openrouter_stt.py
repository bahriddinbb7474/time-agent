"""
Stage 18.1 — mocked tests for OpenRouterSTTProvider.
No real API calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_openrouter_stt.py
"""
import asyncio
import base64
import logging
import os
import tempfile
import unittest.mock as mock
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

import app.services.stt_provider as stt_mod
from app.services.stt_provider import (
    OpenRouterSTTProvider,
    _MAX_ATTEMPTS,
    get_stt_provider,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_resp(
    status: int,
    json_data: dict | None = None,
    text_body: str | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text_body or "")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


class _CapturingHandler(logging.Handler):
    """Captures log records emitted by 'time-agent.stt' during a test."""
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def _make_session(*responses: MagicMock) -> MagicMock:
    session = MagicMock()
    session.post = MagicMock(side_effect=list(responses))
    return session


def _patch_session(session: MagicMock):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return mock.patch.object(stt_mod.aiohttp, "ClientSession", return_value=cm)


def _make_audio(suffix: str = ".ogg"):
    tmp = tempfile.TemporaryDirectory(prefix="stt_test_")
    p = Path(tmp.name) / f"audio{suffix}"
    p.write_bytes(b"fake audio data")
    return tmp, p


def _provider(
    key: str = "sk-test",
    model: str = "openai/whisper-large-v3",
    language: str = "",
):
    return OpenRouterSTTProvider(api_key=key, model=model, language=language)


# ── Test 1: successful OGG transcript ─────────────────────────────────────────

async def test_successful_ogg_transcript() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello world", "usage": {"seconds": 1.2, "cost": 0.0001}})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is True, f"enabled must be True, got {result.enabled}"
        assert result.text == "hello world", f"text mismatch: {result.text!r}"
        assert result.user_message == "Голос расшифрован."
    finally:
        tmp.cleanup()


# ── Test 2: русский текст ─────────────────────────────────────────────────────

async def test_russian_text() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "Позвонить маме сегодня"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is True
        assert result.text == "Позвонить маме сегодня"
    finally:
        tmp.cleanup()


# ── Test 3: узбекский текст ───────────────────────────────────────────────────

async def test_uzbek_text() -> None:
    tmp, audio = _make_audio(".mp3")
    try:
        resp = _make_resp(200, {"text": "Bugun kechqurun uchrashuv bor"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is True
        assert result.text == "Bugun kechqurun uchrashuv bor"
    finally:
        tmp.cleanup()


# ── Test 4: mixed text preserved unchanged ────────────────────────────────────

async def test_mixed_text_preserved() -> None:
    tmp, audio = _make_audio(".wav")
    try:
        mixed = "Сегодня bugun muhim uchrashuv bor в 10 утра"
        resp = _make_resp(200, {"text": mixed})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.text == mixed
    finally:
        tmp.cleanup()


# ── Test 5: empty transcript ──────────────────────────────────────────────────

async def test_empty_transcript() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "   "})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is True, f"enabled must be True, got {result.enabled}"
        assert result.text is None, f"text must be None for empty transcript, got {result.text!r}"
        assert "не смог разобрать" in result.user_message
    finally:
        tmp.cleanup()


# ── Test 6: timeout → one retry, then success ─────────────────────────────────

async def test_timeout_triggers_one_retry() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp_timeout = MagicMock()
        resp_timeout.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
        resp_timeout.__aexit__ = AsyncMock(return_value=False)

        resp_ok = _make_resp(200, {"text": "recovered after timeout"})
        session = _make_session(resp_timeout, resp_ok)
        sleep_mock = AsyncMock()

        with _patch_session(session), mock.patch.object(asyncio, "sleep", sleep_mock):
            result = await _provider().transcribe_audio(audio)

        assert result.enabled is True
        assert result.text == "recovered after timeout"
        assert session.post.call_count == 2, f"expected 2 attempts, got {session.post.call_count}"
        sleep_mock.assert_awaited_once()
    finally:
        tmp.cleanup()


# ── Test 7: HTTP 429 → retry ──────────────────────────────────────────────────

async def test_http_429_triggers_retry() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp_429 = _make_resp(429)
        resp_ok = _make_resp(200, {"text": "ok after 429"})
        session = _make_session(resp_429, resp_ok)

        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)

        assert result.enabled is True
        assert result.text == "ok after 429"
        assert session.post.call_count == 2
    finally:
        tmp.cleanup()


# ── Test 8: HTTP 502 → retry ──────────────────────────────────────────────────

async def test_http_502_triggers_retry() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp_502 = _make_resp(502)
        resp_ok = _make_resp(200, {"text": "ok after 502"})
        session = _make_session(resp_502, resp_ok)

        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)

        assert result.enabled is True
        assert session.post.call_count == 2
    finally:
        tmp.cleanup()


# ── Test 9: HTTP 400 → no retry ───────────────────────────────────────────────

async def test_http_400_no_retry() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp_400 = _make_resp(400)
        session = _make_session(resp_400)

        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)

        assert result.enabled is False
        assert session.post.call_count == 1, f"expected 1 attempt for 400, got {session.post.call_count}"
    finally:
        tmp.cleanup()


# ── Test 10: HTTP 401 → safe error, API key not exposed ───────────────────────

async def test_http_401_safe_error_no_key_leak() -> None:
    secret_key = "sk-super-secret-openrouter-key-xyzzy"
    tmp, audio = _make_audio(".ogg")
    try:
        resp_401 = _make_resp(401)
        session = _make_session(resp_401)

        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider(key=secret_key).transcribe_audio(audio)

        assert result.enabled is False
        assert secret_key not in (result.user_message or "")
        assert secret_key not in (result.text or "")
        assert session.post.call_count == 1
    finally:
        tmp.cleanup()


# ── Test 11: unsupported format → no HTTP call ────────────────────────────────

async def test_unsupported_format() -> None:
    tmp, audio = _make_audio(".xyz")
    try:
        with mock.patch.object(stt_mod.aiohttp, "ClientSession") as mock_cls:
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is False
        assert "поддерживается" in result.user_message
        mock_cls.assert_not_called()
    finally:
        tmp.cleanup()


# ── Test 12: missing OPENROUTER_API_KEY → no HTTP call ───────────────────────

async def test_missing_api_key() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        with mock.patch.object(stt_mod.aiohttp, "ClientSession") as mock_cls:
            result = await OpenRouterSTTProvider(api_key="").transcribe_audio(audio)
        assert result.enabled is False
        mock_cls.assert_not_called()
    finally:
        tmp.cleanup()


# ── Test 13: attempts never exceed _MAX_ATTEMPTS ─────────────────────────────

async def test_attempt_count_never_exceeds_max() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        timeouts = []
        for _ in range(_MAX_ATTEMPTS):
            r = MagicMock()
            r.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
            r.__aexit__ = AsyncMock(return_value=False)
            timeouts.append(r)

        session = _make_session(*timeouts)

        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)

        assert result.enabled is False
        assert session.post.call_count == _MAX_ATTEMPTS, (
            f"expected {_MAX_ATTEMPTS} attempts, got {session.post.call_count}"
        )
    finally:
        tmp.cleanup()


# ── Test 14: factory returns OpenRouterSTTProvider ────────────────────────────

async def test_factory_returns_openrouter_provider() -> None:
    settings = SimpleNamespace(
        stt_provider="openrouter",
        openrouter_api_key="sk-test",
        openrouter_stt_model="openai/whisper-large-v3",
    )
    provider = get_stt_provider(settings)
    assert isinstance(provider, OpenRouterSTTProvider), (
        f"expected OpenRouterSTTProvider, got {type(provider).__name__}"
    )


# ── Test 15: payload schema matches official contract ─────────────────────────

async def test_payload_schema_matches_contract() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            await _provider().transcribe_audio(audio)
        _, kw = session.post.call_args
        payload = kw["json"]
        assert "input_audio" in payload, "payload must have 'input_audio'"
        assert "file" not in payload, "'file' must not be in payload (old field)"
        assert "file_name" not in payload, "'file_name' must not be in payload (old field)"
        ia = payload["input_audio"]
        assert "data" in ia, "input_audio must have 'data'"
        assert "format" in ia, "input_audio must have 'format'"
        assert payload["model"] == "openai/whisper-large-v3"
    finally:
        tmp.cleanup()


# ── Test 16: format field is "ogg", not "audio/ogg" ──────────────────────────

async def test_ogg_format_field_is_short_name() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            await _provider().transcribe_audio(audio)
        _, kw = session.post.call_args
        fmt = kw["json"]["input_audio"]["format"]
        assert fmt == "ogg", f"format must be 'ogg', got {fmt!r}"
        assert "audio/" not in fmt, "format must not contain MIME prefix 'audio/'"
    finally:
        tmp.cleanup()


# ── Test 17: raw base64, no data: URI prefix ──────────────────────────────────

async def test_base64_is_raw_no_data_uri_prefix() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            await _provider().transcribe_audio(audio)
        _, kw = session.post.call_args
        b64val = kw["json"]["input_audio"]["data"]
        assert not b64val.startswith("data:"), "base64 must not start with 'data:'"
        decoded = base64.b64decode(b64val)
        assert decoded == b"fake audio data", "decoded bytes must match original file content"
    finally:
        tmp.cleanup()


# ── Test 18: HTTP 400 error body safely logged (message + code present) ───────

async def test_http_400_error_body_safely_logged() -> None:
    secret_key = "sk-safe-log-test-key-xyzzy"
    tmp, audio = _make_audio(".ogg")
    try:
        err_body = '{"error": {"message": "Invalid input_audio field", "code": "invalid_request"}}'
        resp_400 = _make_resp(400, text_body=err_body)
        session = _make_session(resp_400)

        handler = _CapturingHandler()
        logger = logging.getLogger("time-agent.stt")
        logger.addHandler(handler)
        try:
            with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
                result = await _provider(key=secret_key).transcribe_audio(audio)
        finally:
            logger.removeHandler(handler)

        combined = "\n".join(handler.messages)
        assert "Invalid input_audio field" in combined, "error message must appear in log"
        assert "invalid_request" in combined, "error code must appear in log"
        assert secret_key not in combined, "API key must not appear in any log record"
        assert result.enabled is False
    finally:
        tmp.cleanup()


# ── Test 19: API key and base64 audio data never appear in log records ────────

async def test_key_and_base64_not_in_logs() -> None:
    secret_key = "sk-must-not-appear-in-logs-99999"
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "clean log test"})
        session = _make_session(resp)

        handler = _CapturingHandler()
        logger = logging.getLogger("time-agent.stt")
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
                result = await _provider(key=secret_key).transcribe_audio(audio)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)

        expected_b64 = base64.b64encode(b"fake audio data").decode("ascii")
        combined = "\n".join(handler.messages)
        assert secret_key not in combined, "API key must not appear in any log"
        assert expected_b64 not in combined, "base64 audio data must not appear in any log"
        assert result.enabled is True
        assert result.text == "clean log test"
    finally:
        tmp.cleanup()


# ── Test 21: language=ru is included in payload ───────────────────────────────

async def test_language_ru_included_in_payload() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            await _provider(language="ru").transcribe_audio(audio)
        _, kw = session.post.call_args
        payload = kw["json"]
        assert payload.get("language") == "ru", (
            f"'language' must be 'ru' in payload, got {payload.get('language')!r}"
        )
    finally:
        tmp.cleanup()


# ── Test 22: empty language is absent from payload ────────────────────────────

async def test_empty_language_absent_from_payload() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "hello"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            await _provider(language="").transcribe_audio(audio)
        _, kw = session.post.call_args
        payload = kw["json"]
        assert "language" not in payload, (
            "language key must be absent from payload when not configured"
        )
    finally:
        tmp.cleanup()


# ── Test 23: Russian transcript returned without translation or modification ───

async def test_russian_transcript_returned_unchanged() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        ru_text = "Позвонить маме сегодня вечером"
        resp = _make_resp(200, {"text": ru_text})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider(language="ru").transcribe_audio(audio)
        assert result.enabled is True
        assert result.text == ru_text, (
            f"Russian text must be returned verbatim, got {result.text!r}"
        )
    finally:
        tmp.cleanup()


# ── Test 24: factory passes language to provider ──────────────────────────────

async def test_factory_passes_language_to_provider() -> None:
    settings = SimpleNamespace(
        stt_provider="openrouter",
        openrouter_api_key="sk-test",
        openrouter_stt_model="openai/whisper-large-v3",
        openrouter_stt_language="ru",
    )
    provider = get_stt_provider(settings)
    assert isinstance(provider, OpenRouterSTTProvider)
    assert provider._language == "ru", (
        f"factory must pass language='ru' to provider, got {provider._language!r}"
    )


# ── Test 20: normal successful transcript not broken after fix ────────────────

async def test_success_not_broken_after_fix() -> None:
    tmp, audio = _make_audio(".ogg")
    try:
        resp = _make_resp(200, {"text": "Завтра встреча в десять утра"})
        session = _make_session(resp)
        with _patch_session(session), mock.patch.object(asyncio, "sleep", AsyncMock()):
            result = await _provider().transcribe_audio(audio)
        assert result.enabled is True
        assert result.text == "Завтра встреча в десять утра"
        assert result.user_message == "Голос расшифрован."
    finally:
        tmp.cleanup()


# ── runner ────────────────────────────────────────────────────────────────────

async def main_async() -> None:
    await test_successful_ogg_transcript()
    await test_russian_text()
    await test_uzbek_text()
    await test_mixed_text_preserved()
    await test_empty_transcript()
    await test_timeout_triggers_one_retry()
    await test_http_429_triggers_retry()
    await test_http_502_triggers_retry()
    await test_http_400_no_retry()
    await test_http_401_safe_error_no_key_leak()
    await test_unsupported_format()
    await test_missing_api_key()
    await test_attempt_count_never_exceeds_max()
    await test_factory_returns_openrouter_provider()
    await test_payload_schema_matches_contract()
    await test_ogg_format_field_is_short_name()
    await test_base64_is_raw_no_data_uri_prefix()
    await test_http_400_error_body_safely_logged()
    await test_key_and_base64_not_in_logs()
    await test_success_not_broken_after_fix()
    await test_language_ru_included_in_payload()
    await test_empty_language_absent_from_payload()
    await test_russian_transcript_returned_unchanged()
    await test_factory_passes_language_to_provider()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: OpenRouter STT provider — all 24 tests")


if __name__ == "__main__":
    main()
