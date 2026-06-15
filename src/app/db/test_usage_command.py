"""
Stage 18.6-C — /usage command tests.
Tests aggregation, formatting, timezone, handler safety.
No real API calls. No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_usage_command.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.migration_runner import run_migrations
from app.db.models import ApiUsageRecord, Base
from app.services.api_usage_service import ApiUsageService, DailyUsageSummary
from app.handlers.usage import _format_usage_message


# ─── helpers ──────────────────────────────────────────────────────────────────

def _migration_temp_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_usage_test_")
    db_path = Path(tmp.name) / "test.db"
    run_migrations(db_path)
    return db_path, tmp


async def _make_session(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


async def _insert_row(
    session,
    *,
    usage_date: date,
    service_type: str = "stt",
    status: str = "success",
    request_count: int = 1,
    audio_seconds: float = 0.0,
    estimated_cost_usd: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    provider: str = "openrouter",
    model: str = "openai/whisper-large-v3",
) -> ApiUsageRecord:
    entry = ApiUsageRecord(
        created_at=datetime.now(timezone.utc),
        usage_date=usage_date,
        provider=provider,
        service_type=service_type,
        model=model,
        request_count=request_count,
        audio_seconds=audio_seconds,
        estimated_cost_usd=estimated_cost_usd,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


TODAY = date(2026, 6, 15)
YESTERDAY = date(2026, 6, 14)


# ─── Aggregation tests ────────────────────────────────────────────────────────


async def test_empty_table_returns_zero_summary():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            s = await svc.get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 0
    assert s.request_count == 0
    assert s.success_count == 0
    assert s.error_count == 0
    assert s.limit_exceeded_count == 0
    assert s.stt_request_count == 0
    assert s.stt_audio_seconds == 0.0
    assert s.llm_request_count == 0
    assert s.llm_input_tokens == 0
    assert s.llm_output_tokens == 0
    assert s.estimated_cost_usd == 0.0
    assert s.usage_date == TODAY
    print("PASS: test_empty_table_returns_zero_summary")


async def test_stt_success_row_aggregation():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session,
                usage_date=TODAY,
                service_type="stt",
                status="success",
                audio_seconds=5.5,
                estimated_cost_usd=0.0001,
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 1
    assert s.request_count == 1
    assert s.success_count == 1
    assert s.error_count == 0
    assert s.limit_exceeded_count == 0
    assert s.stt_request_count == 1
    assert abs(s.stt_audio_seconds - 5.5) < 0.001
    assert s.llm_request_count == 0
    assert s.llm_input_tokens == 0
    assert s.llm_output_tokens == 0
    assert abs(s.estimated_cost_usd - 0.0001) < 1e-9
    print("PASS: test_stt_success_row_aggregation")


async def test_stt_error_row_aggregation():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session,
                usage_date=TODAY,
                service_type="stt",
                status="error",
                audio_seconds=3.0,
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.success_count == 0
    assert s.error_count == 1
    assert s.limit_exceeded_count == 0
    assert s.stt_request_count == 1
    print("PASS: test_stt_error_row_aggregation")


async def test_limit_exceeded_row_aggregation():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session,
                usage_date=TODAY,
                service_type="stt",
                status="limit_exceeded",
                audio_seconds=0.0,
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.success_count == 0
    assert s.error_count == 0
    assert s.limit_exceeded_count == 1
    print("PASS: test_limit_exceeded_row_aggregation")


async def test_multiple_stt_rows_summed():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for audio in [4.0, 5.5, 3.2]:
                await _insert_row(
                    session,
                    usage_date=TODAY,
                    service_type="stt",
                    status="success",
                    audio_seconds=audio,
                    estimated_cost_usd=0.0001,
                )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 3
    assert s.request_count == 3
    assert s.success_count == 3
    assert s.stt_request_count == 3
    assert abs(s.stt_audio_seconds - 12.7) < 0.001
    assert abs(s.estimated_cost_usd - 0.0003) < 1e-9
    print("PASS: test_multiple_stt_rows_summed")


async def test_llm_style_rows_with_tokens():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session,
                usage_date=TODAY,
                service_type="llm",
                status="success",
                audio_seconds=0.0,
                input_tokens=1000,
                output_tokens=250,
                estimated_cost_usd=0.005,
                model="openai/gpt-4o-mini",
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 1
    assert s.llm_request_count == 1
    assert s.llm_input_tokens == 1000
    assert s.llm_output_tokens == 250
    assert s.stt_request_count == 0
    assert s.stt_audio_seconds == 0.0
    assert abs(s.estimated_cost_usd - 0.005) < 1e-9
    print("PASS: test_llm_style_rows_with_tokens")


async def test_mixed_stt_and_llm_rows():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session, usage_date=TODAY, service_type="stt",
                status="success", audio_seconds=10.0, estimated_cost_usd=0.0002,
            )
            await _insert_row(
                session, usage_date=TODAY, service_type="stt",
                status="error", audio_seconds=2.0,
            )
            await _insert_row(
                session, usage_date=TODAY, service_type="llm",
                status="success", input_tokens=500, output_tokens=100, estimated_cost_usd=0.003,
                model="openai/gpt-4o-mini",
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 3
    assert s.request_count == 3
    assert s.success_count == 2
    assert s.error_count == 1
    assert s.stt_request_count == 2
    assert abs(s.stt_audio_seconds - 12.0) < 0.001
    assert s.llm_request_count == 1
    assert s.llm_input_tokens == 500
    assert s.llm_output_tokens == 100
    assert abs(s.estimated_cost_usd - 0.0032) < 1e-9
    print("PASS: test_mixed_stt_and_llm_rows")


async def test_cost_sum_across_rows():
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for cost in [0.000100, 0.000200, 0.000050]:
                await _insert_row(
                    session, usage_date=TODAY, service_type="stt",
                    status="success", estimated_cost_usd=cost,
                )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert abs(s.estimated_cost_usd - 0.000350) < 1e-9
    print("PASS: test_cost_sum_across_rows")


async def test_different_dates_isolated():
    """Rows for yesterday must not appear in today's summary."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session, usage_date=YESTERDAY, service_type="stt",
                status="success", audio_seconds=8.0, estimated_cost_usd=0.0005,
            )
            await _insert_row(
                session, usage_date=TODAY, service_type="stt",
                status="success", audio_seconds=3.0, estimated_cost_usd=0.0002,
            )
        async with maker() as session:
            s_today = await ApiUsageService(session).get_daily_summary(TODAY)
            s_yesterday = await ApiUsageService(session).get_daily_summary(YESTERDAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s_today.total_rows == 1
    assert abs(s_today.stt_audio_seconds - 3.0) < 0.001

    assert s_yesterday.total_rows == 1
    assert abs(s_yesterday.stt_audio_seconds - 8.0) < 0.001
    print("PASS: test_different_dates_isolated")


async def test_tashkent_date_query_selects_correct_day():
    """Aggregation uses the passed date, matching Tashkent-based today."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, service_type="stt",
                              status="success", audio_seconds=5.0)
            await _insert_row(session, usage_date=YESTERDAY, service_type="stt",
                              status="success", audio_seconds=9.0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 1
    assert abs(s.stt_audio_seconds - 5.0) < 0.001
    print("PASS: test_tashkent_date_query_selects_correct_day")


async def test_no_none_in_result_for_empty_db():
    """DailyUsageSummary has no None fields even for empty table."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    for field_name in (
        "total_rows", "request_count", "provider_request_count", "no_request_count",
        "success_count", "error_count",
        "limit_exceeded_count", "stt_request_count", "stt_audio_seconds",
        "llm_request_count", "llm_input_tokens", "llm_output_tokens",
        "estimated_cost_usd",
    ):
        val = getattr(s, field_name)
        assert val is not None, f"field {field_name} is None"
    print("PASS: test_no_none_in_result_for_empty_db")


async def test_aggregation_is_read_only():
    """get_daily_summary() does not insert rows."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, service_type="stt",
                              status="success")
        async with maker() as session:
            await ApiUsageService(session).get_daily_summary(TODAY)
        async with maker() as session:
            from sqlalchemy import select as sa_select
            from app.db.models import ApiUsageRecord as AR
            result = await session.execute(sa_select(AR))
            rows = list(result.scalars().all())
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    print("PASS: test_aggregation_is_read_only")


async def test_request_count_field_summed():
    """SUM(request_count) respects the field value (allows future batching)."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(5):
                await _insert_row(session, usage_date=TODAY, service_type="stt",
                                  status="success")
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.request_count == 5
    assert s.total_rows == 5
    print("PASS: test_request_count_field_summed")


# ─── Format tests ─────────────────────────────────────────────────────────────


def test_format_empty_day():
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=0,
        request_count=0,
        provider_request_count=0,
        no_request_count=0,
        success_count=0,
        error_count=0,
        limit_exceeded_count=0,
        stt_request_count=0,
        stt_audio_seconds=0.0,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.0,
    )
    text = _format_usage_message(s)
    assert "📊 API usage — 15.06.2026" in text
    assert "Сегодня API ещё не использовался." in text
    assert "$0.000000" in text
    assert "transcript" not in text.lower()
    assert "sk-" not in text
    print("PASS: test_format_empty_day")


def test_format_stt_only_day():
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=3,
        request_count=3,
        provider_request_count=3,
        no_request_count=0,
        success_count=3,
        error_count=0,
        limit_exceeded_count=0,
        stt_request_count=3,
        stt_audio_seconds=12.4,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.000294,
    )
    text = _format_usage_message(s)
    assert "📊 API usage — 15.06.2026" in text
    assert "Запросы к provider: 3" in text
    assert "✅ Успешно: 3" in text
    assert "❌ Ошибки provider: 0" in text
    assert "⚪ Без вызова provider: 0" in text
    assert "🛑 Hard-limit: 0" in text
    assert "🎙 STT" in text
    assert "12,4 сек" in text
    assert "🧠 LLM" in text
    assert "Input tokens: 0" in text
    assert "$0.000294" in text
    assert "Сегодня API ещё не использовался." not in text
    print("PASS: test_format_stt_only_day")


def test_format_mixed_day():
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=4,
        request_count=4,
        provider_request_count=4,
        no_request_count=0,
        success_count=3,
        error_count=1,
        limit_exceeded_count=0,
        stt_request_count=3,
        stt_audio_seconds=9.6,
        llm_request_count=1,
        llm_input_tokens=1000,
        llm_output_tokens=250,
        estimated_cost_usd=0.005294,
    )
    text = _format_usage_message(s)
    assert "🧠 LLM" in text
    assert "Input tokens: 1000" in text
    assert "Output tokens: 250" in text
    assert "$0.005294" in text
    print("PASS: test_format_mixed_day")


def test_format_no_sensitive_data():
    """Format output must not contain secrets, transcript, or internal IDs."""
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=2,
        request_count=2,
        provider_request_count=2,
        no_request_count=0,
        success_count=2,
        error_count=0,
        limit_exceeded_count=0,
        stt_request_count=2,
        stt_audio_seconds=7.0,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.0001,
    )
    text = _format_usage_message(s)
    for forbidden in ("sk-", "Bearer", "transcript", "Authorization", "api_key"):
        assert forbidden.lower() not in text.lower(), f"forbidden text found: {forbidden!r}"
    print("PASS: test_format_no_sensitive_data")


def test_format_cost_six_decimal_places():
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=1,
        request_count=1,
        provider_request_count=1,
        no_request_count=0,
        success_count=1,
        error_count=0,
        limit_exceeded_count=0,
        stt_request_count=1,
        stt_audio_seconds=5.0,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.000098,
    )
    text = _format_usage_message(s)
    assert "$0.000098" in text
    print("PASS: test_format_cost_six_decimal_places")


def test_format_audio_comma_separator():
    """Audio seconds uses comma (Russian locale) not dot."""
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=1,
        request_count=1,
        provider_request_count=1,
        no_request_count=0,
        success_count=1,
        error_count=0,
        limit_exceeded_count=0,
        stt_request_count=1,
        stt_audio_seconds=12.5,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.0001,
    )
    text = _format_usage_message(s)
    assert "12,5 сек" in text
    assert "12.5 сек" not in text
    print("PASS: test_format_audio_comma_separator")


def test_format_message_length_reasonable():
    """Full message fits within a sensible Telegram character limit."""
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=100,
        request_count=100,
        provider_request_count=100,
        no_request_count=0,
        success_count=95,
        error_count=5,
        limit_exceeded_count=0,
        stt_request_count=80,
        stt_audio_seconds=1234.5,
        llm_request_count=20,
        llm_input_tokens=1_000_000,
        llm_output_tokens=500_000,
        estimated_cost_usd=12.345678,
    )
    text = _format_usage_message(s)
    assert len(text) < 1000, f"message too long: {len(text)} chars"
    print("PASS: test_format_message_length_reasonable")


# ─── Handler tests ────────────────────────────────────────────────────────────


async def test_handler_usage_cmd_success():
    """usage_cmd sends a formatted message and does not raise."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session, usage_date=date.today(), service_type="stt",
                status="success", audio_seconds=5.0, estimated_cost_usd=0.0001,
            )

        from app.handlers.usage import usage_cmd

        class FakeMessage:
            answers: list[str] = []
            async def answer(self, text: str) -> None:
                FakeMessage.answers.append(text)

        FakeMessage.answers = []

        async with maker() as session:
            await usage_cmd(FakeMessage(), session)

        await engine.dispose()
    finally:
        tmp.cleanup()

    assert len(FakeMessage.answers) == 1
    text = FakeMessage.answers[0]
    assert "📊 API usage" in text
    print("PASS: test_handler_usage_cmd_success")


async def test_handler_usage_cmd_empty_day():
    """usage_cmd returns empty-day message when no rows exist for today."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)

        from app.handlers.usage import usage_cmd

        class FakeMessage:
            answers: list[str] = []
            async def answer(self, text: str) -> None:
                FakeMessage.answers.append(text)

        FakeMessage.answers = []

        async with maker() as session:
            await usage_cmd(FakeMessage(), session)

        await engine.dispose()
    finally:
        tmp.cleanup()

    assert len(FakeMessage.answers) == 1
    assert "ещё не использовался" in FakeMessage.answers[0]
    print("PASS: test_handler_usage_cmd_empty_day")


async def test_handler_does_not_insert_rows():
    """usage_cmd must not write any new api_usage rows."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=date.today(), service_type="stt",
                              status="success")

        from app.handlers.usage import usage_cmd
        from sqlalchemy import select as sa_select

        class FakeMessage:
            async def answer(self, text: str) -> None:
                pass

        async with maker() as session:
            await usage_cmd(FakeMessage(), session)

        async with maker() as session:
            result = await session.execute(sa_select(ApiUsageRecord))
            count = len(list(result.scalars().all()))

        await engine.dispose()
    finally:
        tmp.cleanup()

    assert count == 1, f"expected 1 row, got {count} — handler must not write usage rows"
    print("PASS: test_handler_does_not_insert_rows")


async def test_handler_db_error_returns_safe_message():
    """When DB raises, usage_cmd answers with a generic safe message (no traceback)."""
    from app.handlers.usage import usage_cmd

    class BrokenSession:
        async def execute(self, *a, **kw):
            raise RuntimeError("simulated DB failure")

    class FakeMessage:
        answers: list[str] = []
        async def answer(self, text: str) -> None:
            FakeMessage.answers.append(text)

    FakeMessage.answers = []
    await usage_cmd(FakeMessage(), BrokenSession())

    assert len(FakeMessage.answers) == 1
    text = FakeMessage.answers[0]
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    assert "Не удалось" in text
    print("PASS: test_handler_db_error_returns_safe_message")


# ─── Timezone tests ───────────────────────────────────────────────────────────


def test_now_tz_returns_tashkent_date():
    """now_tz().date() returns a date object (correct Tashkent timezone usage)."""
    from app.core.time import now_tz
    from zoneinfo import ZoneInfo
    tz_result = now_tz()
    assert tz_result.tzinfo is not None
    assert isinstance(tz_result.date(), date)
    assert str(tz_result.tzinfo) == "Asia/Tashkent"
    print("PASS: test_now_tz_returns_tashkent_date")


async def test_midnight_boundary_date_isolation():
    """Records for two consecutive days are counted separately."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        d1 = date(2026, 6, 14)
        d2 = date(2026, 6, 15)
        async with maker() as session:
            await _insert_row(session, usage_date=d1, service_type="stt",
                              status="success", audio_seconds=1.0)
            await _insert_row(session, usage_date=d2, service_type="stt",
                              status="success", audio_seconds=2.0)
        async with maker() as session:
            s1 = await ApiUsageService(session).get_daily_summary(d1)
            s2 = await ApiUsageService(session).get_daily_summary(d2)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s1.total_rows == 1 and abs(s1.stt_audio_seconds - 1.0) < 0.001
    assert s2.total_rows == 1 and abs(s2.stt_audio_seconds - 2.0) < 0.001
    print("PASS: test_midnight_boundary_date_isolation")


async def test_future_date_returns_zeros():
    """Querying a future date with no rows returns all-zeros summary."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, service_type="stt",
                              status="success", audio_seconds=5.0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(date(2030, 1, 1))
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 0
    assert s.estimated_cost_usd == 0.0
    print("PASS: test_future_date_returns_zeros")


# ─── Provider request / no-request tests ─────────────────────────────────────


async def test_provider_request_count_is_rows_with_rc_gt_zero():
    """provider_request_count counts rows where request_count > 0."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="error", request_count=1)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.provider_request_count == 2
    assert s.no_request_count == 0
    print("PASS: test_provider_request_count_is_rows_with_rc_gt_zero")


async def test_no_request_count_counts_rc_zero_rows():
    """no_request_count counts rows where request_count = 0 (inserted directly)."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            # Insert row with request_count=0 directly (bypasses service validator,
            # exercises DB-level aggregation for future Stage 18.6-D no-HTTP-call rows)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.no_request_count == 1, f"expected 1 no-request row, got {s.no_request_count}"
    assert s.provider_request_count == 1, f"expected 1 provider row, got {s.provider_request_count}"
    print("PASS: test_no_request_count_counts_rc_zero_rows")


async def test_limit_exceeded_shown_separately_not_double_counted():
    """limit_exceeded rows appear in limit_exceeded_count; no_request_count tracks RC=0."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.limit_exceeded_count == 1, (
        f"limit_exceeded_count must count limit_exceeded rows regardless of RC; "
        f"expected 1, got {s.limit_exceeded_count}"
    )
    assert s.no_request_count == 1
    assert s.provider_request_count == 1
    assert s.total_rows == 2
    print("PASS: test_limit_exceeded_shown_separately_not_double_counted")


async def test_stt_request_count_uses_provider_requests_not_total_rows():
    """STT request count uses SUM(request_count) for STT rows, not COUNT(*) of rows."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(
                session, usage_date=TODAY, service_type="stt",
                status="success", request_count=1, audio_seconds=5.0,
            )
            await _insert_row(
                session, usage_date=TODAY, service_type="stt",
                status="limit_exceeded", request_count=0, audio_seconds=0.0,
            )
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.stt_request_count == 1, (
        f"stt_request_count must be SUM(request_count) for STT rows = 1, got {s.stt_request_count}"
    )
    assert s.total_rows == 2
    print("PASS: test_stt_request_count_uses_provider_requests_not_total_rows")


async def test_mixed_rows_no_request_and_provider():
    """Mixed day: provider rows + no-request rows; each category is independent."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="error", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 3
    assert s.provider_request_count == 2
    assert s.no_request_count == 1
    assert s.success_count == 1
    assert s.error_count == 1
    print("PASS: test_mixed_rows_no_request_and_provider")


async def test_format_shows_bez_vyzova_provider():
    """Format output includes 'Без вызова provider' label."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    text = _format_usage_message(s)
    assert "Без вызова provider: 1" in text, f"expected 'Без вызова provider: 1' in:\n{text}"
    assert "Hard-limit: 1" in text, f"expected 'Hard-limit: 1' in:\n{text}"
    print("PASS: test_format_shows_bez_vyzova_provider")


async def test_format_provider_request_label_not_just_zaprosы():
    """Format uses 'Запросы к provider:' not bare 'Запросы:'."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    text = _format_usage_message(s)
    assert "Запросы к provider:" in text
    assert "Ошибки provider:" in text
    print("PASS: test_format_provider_request_label_not_just_zaprosы")


# ─── Hard-limit count tests ───────────────────────────────────────────────────


async def test_single_hard_limit_event_with_rc_zero():
    """Single limit_exceeded row with RC=0 → limit_exceeded_count=1."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.limit_exceeded_count == 1, f"expected 1, got {s.limit_exceeded_count}"
    assert s.no_request_count == 1
    assert s.provider_request_count == 0
    assert s.success_count == 0
    assert s.error_count == 0
    print("PASS: test_single_hard_limit_event_with_rc_zero")


async def test_multiple_hard_limit_events_counted():
    """Multiple limit_exceeded rows with RC=0 are all counted."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.limit_exceeded_count == 3, f"expected 3, got {s.limit_exceeded_count}"
    assert s.no_request_count == 3
    assert s.total_rows == 3
    print("PASS: test_multiple_hard_limit_events_counted")


async def test_mixed_scenario_all_categories():
    """Mixed rows: success/RC=1, error/RC=1, limit_exceeded/RC=0, error/RC=0."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_row(session, usage_date=TODAY, status="success", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="error", request_count=1)
            await _insert_row(session, usage_date=TODAY, status="limit_exceeded", request_count=0)
            await _insert_row(session, usage_date=TODAY, status="error", request_count=0)
        async with maker() as session:
            s = await ApiUsageService(session).get_daily_summary(TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert s.total_rows == 4
    assert s.provider_request_count == 2, f"expected 2, got {s.provider_request_count}"
    assert s.no_request_count == 2, f"expected 2, got {s.no_request_count}"
    assert s.success_count == 1
    assert s.error_count == 1  # only the RC=1 error row
    assert s.limit_exceeded_count == 1, f"expected 1, got {s.limit_exceeded_count}"
    print("PASS: test_mixed_scenario_all_categories")


def test_format_hard_limit_nonzero_shown():
    """Format shows non-zero hard-limit count correctly."""
    s = DailyUsageSummary(
        usage_date=date(2026, 6, 15),
        total_rows=3,
        request_count=1,
        provider_request_count=1,
        no_request_count=2,
        success_count=1,
        error_count=0,
        limit_exceeded_count=2,
        stt_request_count=1,
        stt_audio_seconds=5.0,
        llm_request_count=0,
        llm_input_tokens=0,
        llm_output_tokens=0,
        estimated_cost_usd=0.0001,
    )
    text = _format_usage_message(s)
    assert "🛑 Hard-limit: 2" in text, f"expected '🛑 Hard-limit: 2' in:\n{text}"
    assert "⚪ Без вызова provider: 2" in text
    print("PASS: test_format_hard_limit_nonzero_shown")


# ─── Tashkent usage_date tests ────────────────────────────────────────────────


async def test_tashkent_midnight_boundary_before():
    """18:59 UTC = 23:59 Tashkent → usage_date is June 15 (same day)."""
    from datetime import timezone as tz
    from zoneinfo import ZoneInfo
    from app.services.api_usage_service import ApiUsageService as Svc

    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        ts = datetime(2026, 6, 15, 18, 59, 0, tzinfo=tz.utc)
        async with maker() as session:
            row = await Svc(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert row.usage_date == date(2026, 6, 15), (
        f"18:59 UTC = 23:59 Tashkent, expected 2026-06-15, got {row.usage_date}"
    )
    print("PASS: test_tashkent_midnight_boundary_before")


async def test_tashkent_midnight_boundary_at():
    """19:00 UTC = 00:00 Tashkent → usage_date advances to June 16."""
    from datetime import timezone as tz
    from app.services.api_usage_service import ApiUsageService as Svc

    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        ts = datetime(2026, 6, 15, 19, 0, 0, tzinfo=tz.utc)
        async with maker() as session:
            row = await Svc(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert row.usage_date == date(2026, 6, 16), (
        f"19:00 UTC = 00:00 Tashkent next day, expected 2026-06-16, got {row.usage_date}"
    )
    print("PASS: test_tashkent_midnight_boundary_at")


async def test_tashkent_midnight_boundary_after():
    """20:30 UTC = 01:30 Tashkent → usage_date is June 16."""
    from datetime import timezone as tz
    from app.services.api_usage_service import ApiUsageService as Svc

    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        ts = datetime(2026, 6, 15, 20, 30, 0, tzinfo=tz.utc)
        async with maker() as session:
            row = await Svc(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        await engine.dispose()
    finally:
        tmp.cleanup()

    assert row.usage_date == date(2026, 6, 16), (
        f"20:30 UTC = 01:30 Tashkent, expected 2026-06-16, got {row.usage_date}"
    )
    print("PASS: test_tashkent_midnight_boundary_after")


# ─── Test runner ─────────────────────────────────────────────────────────────

SYNC_TESTS = [
    test_format_empty_day,
    test_format_stt_only_day,
    test_format_mixed_day,
    test_format_no_sensitive_data,
    test_format_cost_six_decimal_places,
    test_format_audio_comma_separator,
    test_format_message_length_reasonable,
    test_now_tz_returns_tashkent_date,
    test_format_hard_limit_nonzero_shown,
]

ASYNC_TESTS = [
    test_empty_table_returns_zero_summary,
    test_stt_success_row_aggregation,
    test_stt_error_row_aggregation,
    test_limit_exceeded_row_aggregation,
    test_multiple_stt_rows_summed,
    test_llm_style_rows_with_tokens,
    test_mixed_stt_and_llm_rows,
    test_cost_sum_across_rows,
    test_different_dates_isolated,
    test_tashkent_date_query_selects_correct_day,
    test_no_none_in_result_for_empty_db,
    test_aggregation_is_read_only,
    test_request_count_field_summed,
    test_handler_usage_cmd_success,
    test_handler_usage_cmd_empty_day,
    test_handler_does_not_insert_rows,
    test_handler_db_error_returns_safe_message,
    test_midnight_boundary_date_isolation,
    test_future_date_returns_zeros,
    # Provider request / no-request
    test_provider_request_count_is_rows_with_rc_gt_zero,
    test_no_request_count_counts_rc_zero_rows,
    test_limit_exceeded_shown_separately_not_double_counted,
    test_stt_request_count_uses_provider_requests_not_total_rows,
    test_mixed_rows_no_request_and_provider,
    test_format_shows_bez_vyzova_provider,
    test_format_provider_request_label_not_just_zaprosы,
    # Hard-limit count
    test_single_hard_limit_event_with_rc_zero,
    test_multiple_hard_limit_events_counted,
    test_mixed_scenario_all_categories,
    # Tashkent usage_date boundary
    test_tashkent_midnight_boundary_before,
    test_tashkent_midnight_boundary_at,
    test_tashkent_midnight_boundary_after,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()

    async def run_async():
        for fn in ASYNC_TESTS:
            await fn()

    asyncio.run(run_async())

    total = len(SYNC_TESTS) + len(ASYNC_TESTS)
    print(f"PASS: all {total} /usage tests passed")


if __name__ == "__main__":
    main()
