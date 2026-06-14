"""
Stage 18.1 — mocked tests for OpenRouterSTTProvider.
No real API calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_openrouter_stt.py
"""
import asyncio
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


def _make_resp(status: int, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


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


def _provider(key: str = "sk-test", model: str = "openai/whisper-large-v3"):
    return OpenRouterSTTProvider(api_key=key, model=model)


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


def main() -> None:
    asyncio.run(main_async())
    print("PASS: OpenRouter STT provider — all 14 tests")


if __name__ == "__main__":
    main()
