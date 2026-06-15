"""
Stage 18.6-D — ApiLimitService unit tests.
No real API calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_api_limit_service.py
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
from app.services.api_usage_service import ApiUsageService
from app.services.api_limit_service import (
    ApiLimitDecision,
    ApiLimitService,
    REASON_LLM_COST_LIMIT,
    REASON_LLM_REQUEST_LIMIT,
    REASON_STT_REQUEST_LIMIT,
    REASON_STT_SECONDS_LIMIT,
)

TODAY = date(2026, 6, 16)
YESTERDAY = date(2026, 6, 15)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _migration_temp_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_limit_svc_")
    db_path = Path(tmp.name) / "test.db"
    run_migrations(db_path)
    return db_path, tmp


async def _make_session(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


def _cfg(
    stt_request=0,
    stt_seconds=0,
    llm_request=0,
    llm_cost=0.0,
):
    return SimpleNamespace(
        stt_daily_request_limit=stt_request,
        stt_daily_seconds_limit=stt_seconds,
        llm_daily_request_limit=llm_request,
        llm_daily_cost_usd_limit=llm_cost,
    )


async def _insert_stt(session, *, usage_date, status="success", audio_seconds=5.0, request_count=1):
    entry = ApiUsageRecord(
        created_at=datetime.now(timezone.utc),
        usage_date=usage_date,
        provider="openrouter",
        service_type="stt",
        model="openai/whisper-large-v3",
        request_count=request_count,
        audio_seconds=audio_seconds,
        estimated_cost_usd=0.0001,
        status=status,
        input_tokens=0,
        output_tokens=0,
    )
    session.add(entry)
    await session.commit()


async def _insert_llm(session, *, usage_date, status="success", request_count=1, cost=0.005):
    entry = ApiUsageRecord(
        created_at=datetime.now(timezone.utc),
        usage_date=usage_date,
        provider="openrouter",
        service_type="llm",
        model="openai/gpt-4o-mini",
        request_count=request_count,
        audio_seconds=0.0,
        estimated_cost_usd=cost,
        status=status,
        input_tokens=100,
        output_tokens=50,
    )
    session.add(entry)
    await session.commit()


# ── STT limit tests ───────────────────────────────────────────────────────────


async def test_empty_day_allowed():
    """No usage today → all checks pass with any reasonable limit."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            svc = ApiLimitService(session, _cfg(stt_request=10, stt_seconds=600))
            d = await svc.check_stt(planned_seconds=5.0, usage_date=TODAY)
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, f"empty day must be allowed, got {d}"
    print("PASS: test_empty_day_allowed")


async def test_stt_below_request_limit_allowed():
    """current=4, limit=10, +1 → allowed."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(4):
                await _insert_stt(session, usage_date=TODAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed
    print("PASS: test_stt_below_request_limit_allowed")


async def test_stt_request_limit_last_slot_allowed():
    """current=9, limit=10, +1 → allowed (exactly reaches limit)."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(9):
                await _insert_stt(session, usage_date=TODAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, f"9 used of 10 limit, +1 must be allowed, got {d}"
    print("PASS: test_stt_request_limit_last_slot_allowed")


async def test_stt_request_limit_exceeded():
    """current=10, limit=10, +1 → blocked."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(10):
                await _insert_stt(session, usage_date=TODAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed
    assert d.reason == REASON_STT_REQUEST_LIMIT
    assert d.current_value == 10
    assert d.limit_value == 10
    print("PASS: test_stt_request_limit_exceeded")


async def test_stt_audio_seconds_last_slot_allowed():
    """current=595s, limit=600s, +4s → allowed."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_stt(session, usage_date=TODAY, audio_seconds=595.0)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_seconds=600)).check_stt(
                planned_seconds=4.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, f"595+4=599 <= 600, must be allowed, got {d}"
    print("PASS: test_stt_audio_seconds_last_slot_allowed")


async def test_stt_audio_seconds_limit_exceeded():
    """current=599s, limit=600s, +2s → blocked."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_stt(session, usage_date=TODAY, audio_seconds=599.0)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_seconds=600)).check_stt(
                planned_seconds=2.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed
    assert d.reason == REASON_STT_SECONDS_LIMIT
    assert abs(d.current_value - 599.0) < 0.001
    assert d.limit_value == 600
    print("PASS: test_stt_audio_seconds_limit_exceeded")


async def test_stt_zero_limit_means_unlimited():
    """limit=0 → no limit enforced, even with many requests."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(100):
                await _insert_stt(session, usage_date=TODAY, audio_seconds=600.0)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=0, stt_seconds=0)).check_stt(
                planned_seconds=999.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, f"limit=0 must be unlimited, got {d}"
    print("PASS: test_stt_zero_limit_means_unlimited")


async def test_different_dates_isolated():
    """Yesterday's usage does not count toward today's limit."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(10):
                await _insert_stt(session, usage_date=YESTERDAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, "yesterday's usage must not count toward today's limit"
    print("PASS: test_different_dates_isolated")


async def test_limit_exceeded_rows_not_counted_as_provider_requests():
    """limit_exceeded rows (RC=0) don't consume provider request quota."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            # 9 real requests
            for _ in range(9):
                await svc.record_stt(
                    provider="openrouter", model="openai/whisper-large-v3",
                    audio_seconds=5.0, status="success",
                )
            # 5 limit_exceeded events (should not count)
            for _ in range(5):
                await svc.record_limit_exceeded(
                    provider="openrouter", service_type="stt",
                    model="openai/whisper-large-v3",
                )
            await session.commit()
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, f"9 real + 5 limit_exceeded events should leave 1 slot; got {d}"
    print("PASS: test_limit_exceeded_rows_not_counted_as_provider_requests")


async def test_error_rows_count_as_provider_requests():
    """Error rows (RC=1) DO consume provider request quota."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(10):
                await _insert_stt(session, usage_date=TODAY, status="error")
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed, "10 error rows must exhaust a limit=10"
    print("PASS: test_error_rows_count_as_provider_requests")


async def test_stt_reason_code_is_structured():
    """Blocked decision carries a stable reason code string."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(5):
                await _insert_stt(session, usage_date=TODAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=5)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.reason == REASON_STT_REQUEST_LIMIT
    assert d.limit_name == "STT_DAILY_REQUEST_LIMIT"
    print("PASS: test_stt_reason_code_is_structured")


async def test_allowed_decision_has_no_reason():
    """Allowed decision has reason=None and limit_name=None."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed
    assert d.reason is None
    assert d.limit_name is None
    print("PASS: test_allowed_decision_has_no_reason")


async def test_service_is_read_only():
    """check_stt() does not insert any rows."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await ApiLimitService(session, _cfg(stt_request=10)).check_stt(
                planned_seconds=5.0, usage_date=TODAY
            )
        async with maker() as session:
            from sqlalchemy import select
            count = (await session.execute(select(ApiUsageRecord))).scalars().all()
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert len(count) == 0, f"check_stt must not write rows, got {len(count)}"
    print("PASS: test_service_is_read_only")


# ── LLM limit tests ───────────────────────────────────────────────────────────


async def test_llm_request_limit_exceeded():
    """LLM request limit: current=5, limit=5, +1 → blocked."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(5):
                await _insert_llm(session, usage_date=TODAY)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(llm_request=5)).check_llm(
                planned_requests=1, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed
    assert d.reason == REASON_LLM_REQUEST_LIMIT
    print("PASS: test_llm_request_limit_exceeded")


async def test_llm_cost_limit_exceeded():
    """LLM cost limit: current=0.009, limit=0.01, +0.002 → blocked."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            await _insert_llm(session, usage_date=TODAY, cost=0.009)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(llm_cost=0.01)).check_llm(
                planned_requests=1, planned_cost_usd=0.002, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed
    assert d.reason == REASON_LLM_COST_LIMIT
    print("PASS: test_llm_cost_limit_exceeded")


async def test_llm_zero_limit_means_unlimited():
    """LLM limit=0 → no limit enforced."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            for _ in range(100):
                await _insert_llm(session, usage_date=TODAY, cost=10.0)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(llm_request=0, llm_cost=0.0)).check_llm(
                planned_requests=1, planned_cost_usd=999.0, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, "LLM limit=0 must be unlimited"
    print("PASS: test_llm_zero_limit_means_unlimited")


async def test_stt_cost_does_not_count_toward_llm_cost_limit():
    """STT costs are excluded from llm_estimated_cost_usd; LLM limit not triggered by STT costs."""
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        async with maker() as session:
            # Insert expensive STT costs
            for _ in range(5):
                await _insert_stt(session, usage_date=TODAY, audio_seconds=10.0)
        async with maker() as session:
            # LLM cost limit is low, but no LLM rows exist
            d = await ApiLimitService(session, _cfg(llm_cost=0.001)).check_llm(
                planned_requests=1, planned_cost_usd=0.0009, usage_date=TODAY
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert d.allowed, "STT costs must not count toward LLM cost limit"
    print("PASS: test_stt_cost_does_not_count_toward_llm_cost_limit")


async def test_tashkent_midnight_usage_date():
    """Records for today's date match when using Tashkent date for query."""
    from zoneinfo import ZoneInfo
    db_path, tmp = _migration_temp_db()
    try:
        engine, maker = await _make_session(db_path)
        tz = ZoneInfo("Asia/Tashkent")
        from datetime import datetime
        today_tashkent = datetime.now(tz=tz).date()

        async with maker() as session:
            for _ in range(5):
                await _insert_stt(session, usage_date=today_tashkent)
        async with maker() as session:
            d = await ApiLimitService(session, _cfg(stt_request=5)).check_stt(
                planned_seconds=5.0, usage_date=today_tashkent
            )
        await engine.dispose()
    finally:
        tmp.cleanup()
    assert not d.allowed, "5 used of 5 limit in Tashkent date → blocked"
    print("PASS: test_tashkent_midnight_usage_date")


# ── runner ────────────────────────────────────────────────────────────────────


ASYNC_TESTS = [
    test_empty_day_allowed,
    test_stt_below_request_limit_allowed,
    test_stt_request_limit_last_slot_allowed,
    test_stt_request_limit_exceeded,
    test_stt_audio_seconds_last_slot_allowed,
    test_stt_audio_seconds_limit_exceeded,
    test_stt_zero_limit_means_unlimited,
    test_different_dates_isolated,
    test_limit_exceeded_rows_not_counted_as_provider_requests,
    test_error_rows_count_as_provider_requests,
    test_stt_reason_code_is_structured,
    test_allowed_decision_has_no_reason,
    test_service_is_read_only,
    test_llm_request_limit_exceeded,
    test_llm_cost_limit_exceeded,
    test_llm_zero_limit_means_unlimited,
    test_stt_cost_does_not_count_toward_llm_cost_limit,
    test_tashkent_midnight_usage_date,
]


def main() -> None:
    async def run():
        for fn in ASYNC_TESTS:
            await fn()

    asyncio.run(run())
    print(f"\nALL {len(ASYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
