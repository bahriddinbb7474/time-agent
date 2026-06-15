"""
Stage 18.6-D — STT hard-limit integration tests.
Tests the full path: capture handler → ApiLimitService → DB (preflight) → STT provider.
No real HTTP calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_stt_hard_limit_integration.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest.mock as mock
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ApiUsageRecord, Base
from app.handlers.capture import capture_voice_message
from app.services.api_usage_service import ApiUsageService
from app.services.stt_provider import (
    OpenRouterSTTProvider,
    STTResult,
    STTUsageInfo,
)

CHAT_ID = 555
USER_ID = 123456789


# ── Fake infrastructure ───────────────────────────────────────────────────────


def _settings(*, stt_request_limit=0, stt_seconds_limit=0):
    return SimpleNamespace(
        stt_max_duration_sec=60,
        stt_max_file_mb=10,
        openrouter_stt_model="openai/whisper-large-v3",
        stt_daily_request_limit=stt_request_limit,
        stt_daily_seconds_limit=stt_seconds_limit,
        llm_daily_request_limit=0,
        llm_daily_cost_usd_limit=0.0,
    )


class FakeVoice:
    file_id = "voice-file-id"

    def __init__(self, *, duration: int = 10, file_size: int = 1024):
        self.duration = duration
        self.file_size = file_size


class FakeFile:
    file_path = "telegram/voice.ogg"


class FakeBot:
    def __init__(self):
        self.get_file_calls = 0
        self.download_file_calls = 0

    async def get_file(self, file_id: str):
        self.get_file_calls += 1
        return FakeFile()

    async def download_file(self, file_path: str, *, destination: Path):
        self.download_file_calls += 1
        destination.write_bytes(b"fake voice data")


class FakeChat:
    id = CHAT_ID


class FakeUser:
    id = USER_ID


class FakeVoiceMessage:
    def __init__(self, *, voice: FakeVoice | None = None):
        self.voice = voice or FakeVoice()
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)


class FakeOpenRouterProvider(OpenRouterSTTProvider):
    """Returns a canned transcription result without making HTTP calls."""

    def __init__(self, *, text: str = "купить молоко", request_made: bool = True):
        super().__init__(api_key="sk-test", model="openai/whisper-large-v3")
        self.transcribe_call_count = 0
        self._text = text
        self._request_made = request_made

    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        self.transcribe_call_count += 1
        return STTResult(
            enabled=True,
            text=self._text,
            user_message="",
            usage=STTUsageInfo(audio_seconds=10.0, estimated_cost_usd=0.001),
            request_made=self._request_made,
        )


async def _make_session():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_stt_limit_")
    db_path = Path(tmp.name) / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return tmp, engine, maker


async def _count_usage_rows(session) -> int:
    rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
    return len(rows)


async def _count_limit_exceeded_rows(session) -> int:
    rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
    return sum(1 for r in rows if r.status == "limit_exceeded")


async def _insert_stt_success(maker):
    """Insert one success row in its own session (using service to get correct Tashkent date)."""
    async with maker() as session:
        await ApiUsageService(session).record_stt(
            provider="openrouter",
            model="openai/whisper-large-v3",
            audio_seconds=10.0,
            estimated_cost_usd=0.001,
            status="success",
        )
        await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_unlimited_config_calls_provider():
    """When limits are 0 (unlimited), the STT provider is called normally."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=0, stt_seconds_limit=0),
                stt_provider=provider,
            )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert provider.transcribe_call_count == 1, (
        f"provider must be called once when unlimited, got {provider.transcribe_call_count}"
    )
    limit_msgs = [a for a in msg.answers if "Лимит" in a]
    assert not limit_msgs, f"no limit message expected, got {limit_msgs}"
    print("PASS: test_unlimited_config_calls_provider")


async def test_request_limit_blocks_provider_call():
    """When request limit is met, provider must NOT be called."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        for _ in range(3):
            await _insert_stt_success(maker)

        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=3),
                stt_provider=provider,
            )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert provider.transcribe_call_count == 0, (
        f"provider must NOT be called when limit is met, got {provider.transcribe_call_count}"
    )
    print("PASS: test_request_limit_blocks_provider_call")


async def test_request_limit_sends_block_message_to_user():
    """When request limit is met, user receives the Russian limit message."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        for _ in range(2):
            await _insert_stt_success(maker)

        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=2),
                stt_provider=provider,
            )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert len(msg.answers) >= 1, "user must receive at least one message when blocked"
    limit_msgs = [a for a in msg.answers if "Лимит" in a]
    assert limit_msgs, f"expected limit message, got {msg.answers}"
    print("PASS: test_request_limit_sends_block_message_to_user")


async def test_request_limit_records_limit_exceeded_row():
    """When blocked by request limit, a limit_exceeded row is recorded in DB."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        await _insert_stt_success(maker)

        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=1),
                stt_provider=provider,
            )

        async with maker() as session:
            le_count = await _count_limit_exceeded_rows(session)
            total = await _count_usage_rows(session)
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert le_count == 1, f"expected 1 limit_exceeded row, got {le_count}"
    assert total == 2, f"expected 2 total rows (1 success + 1 limit_exceeded), got {total}"
    print("PASS: test_request_limit_records_limit_exceeded_row")


async def test_seconds_limit_blocks_provider_call():
    """When audio seconds limit would be exceeded, provider must NOT be called."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage(voice=FakeVoice(duration=30))
    try:
        async with maker() as session:
            await ApiUsageService(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=580.0,
                estimated_cost_usd=0.001,
                status="success",
            )
            await session.commit()

        async with maker() as session:
            # limit=600, used=580, planned=30 → 580+30=610 > 600 → blocked
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_seconds_limit=600),
                stt_provider=provider,
            )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert provider.transcribe_call_count == 0, (
        "provider must NOT be called when seconds limit is exceeded"
    )
    limit_msgs = [a for a in msg.answers if "Лимит" in a]
    assert limit_msgs, f"expected limit message, got {msg.answers}"
    print("PASS: test_seconds_limit_blocks_provider_call")


async def test_db_error_in_limit_check_allows_request_fail_open():
    """DB error during preflight check must not block owner (fail-open per canonical TZ §18.6-D)."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        async with maker() as session:
            with mock.patch(
                "app.services.api_usage_service.ApiUsageService.get_daily_summary",
                side_effect=RuntimeError("DB connection lost"),
            ):
                await capture_voice_message(
                    msg,
                    session=session,
                    settings=_settings(stt_request_limit=1),
                    stt_provider=provider,
                )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert provider.transcribe_call_count == 1, (
        f"fail-open: provider must be called even when limit check fails, "
        f"got transcribe_call_count={provider.transcribe_call_count}"
    )
    limit_msgs = [a for a in msg.answers if "Лимит" in a]
    assert not limit_msgs, f"fail-open: no limit message should be sent, got {msg.answers}"
    print("PASS: test_db_error_in_limit_check_allows_request_fail_open")


async def test_limit_exceeded_rows_not_counted_in_preflight():
    """limit_exceeded rows (RC=0) must not be counted when evaluating the next request."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        # Insert 4 success + 10 limit_exceeded rows; limit=5 → 5th real request allowed
        for _ in range(4):
            await _insert_stt_success(maker)

        async with maker() as session:
            svc = ApiUsageService(session)
            for _ in range(10):
                await svc.record_limit_exceeded(
                    provider="openrouter",
                    service_type="stt",
                    model="openai/whisper-large-v3",
                )
            await session.commit()

        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=5),
                stt_provider=provider,
            )
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert provider.transcribe_call_count == 1, (
        f"limit_exceeded rows must not count against quota; "
        f"got transcribe_call_count={provider.transcribe_call_count}"
    )
    limit_msgs = [a for a in msg.answers if "Лимит" in a]
    assert not limit_msgs, f"should not be blocked, got {msg.answers}"
    print("PASS: test_limit_exceeded_rows_not_counted_in_preflight")


async def test_below_limit_does_not_record_limit_exceeded():
    """Successful request must not leave any limit_exceeded rows."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=10),
                stt_provider=provider,
            )

        async with maker() as session:
            le_count = await _count_limit_exceeded_rows(session)
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert le_count == 0, f"no limit_exceeded rows expected after allowed request, got {le_count}"
    print("PASS: test_below_limit_does_not_record_limit_exceeded")


async def test_limit_exceeded_row_has_correct_fields():
    """limit_exceeded row must have request_count=0, audio_seconds=0, status='limit_exceeded'."""
    tmp, engine, maker = await _make_session()
    provider = FakeOpenRouterProvider()
    msg = FakeVoiceMessage()
    try:
        await _insert_stt_success(maker)

        async with maker() as session:
            await capture_voice_message(
                msg,
                session=session,
                settings=_settings(stt_request_limit=1),
                stt_provider=provider,
            )

        async with maker() as session:
            rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
            le_row = next((r for r in rows if r.status == "limit_exceeded"), None)
    finally:
        await engine.dispose()
        tmp.cleanup()

    assert le_row is not None, "limit_exceeded row must be recorded"
    assert le_row.request_count == 0, f"expected request_count=0, got {le_row.request_count}"
    assert le_row.audio_seconds == 0.0, f"expected audio_seconds=0.0, got {le_row.audio_seconds}"
    assert le_row.estimated_cost_usd == 0.0, f"expected cost=0.0, got {le_row.estimated_cost_usd}"
    assert le_row.service_type == "stt"
    assert le_row.provider == "openrouter"
    print("PASS: test_limit_exceeded_row_has_correct_fields")


# ── runner ────────────────────────────────────────────────────────────────────


ASYNC_TESTS = [
    test_unlimited_config_calls_provider,
    test_request_limit_blocks_provider_call,
    test_request_limit_sends_block_message_to_user,
    test_request_limit_records_limit_exceeded_row,
    test_seconds_limit_blocks_provider_call,
    test_db_error_in_limit_check_allows_request_fail_open,
    test_limit_exceeded_rows_not_counted_in_preflight,
    test_below_limit_does_not_record_limit_exceeded,
    test_limit_exceeded_row_has_correct_fields,
]


def main() -> None:
    async def run():
        for fn in ASYNC_TESTS:
            await fn()

    asyncio.run(run())
    print(f"\nALL {len(ASYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
