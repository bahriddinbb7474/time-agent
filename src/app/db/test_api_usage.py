"""
Stage 18.6-A — api_usage schema, ORM model, and service tests.
No real API calls, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_api_usage.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.migration_runner import run_migrations
from app.db.models import ApiUsageRecord, Base
from app.services.api_usage_service import ApiUsageService, ApiUsageValidationError


# ─── helpers ──────────────────────────────────────────────────────────────────


def _migration_temp_db():
    """Run all migrations into a temp file DB. Caller must call tmp.cleanup()."""
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_api_usage_mig_")
    db_path = Path(tmp.name) / "mig.db"
    run_migrations(db_path)
    return db_path, tmp


async def _make_engine(db_path: Path):
    """Create async engine on db_path with all ORM tables ensured."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


def _mock_session() -> MagicMock:
    """Minimal mock session for validation-only tests (no DB calls happen)."""
    session = MagicMock()
    session.flush = AsyncMock()
    return session


async def _expect_validation_error(coro) -> None:
    try:
        await coro
        raise AssertionError("expected ApiUsageValidationError but none was raised")
    except ApiUsageValidationError:
        pass


# ─── Migration tests (sync) ───────────────────────────────────────────────────


def test_migration_creates_table():
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(api_usage)").fetchall()}
            expected = {
                "id", "created_at", "usage_date", "provider", "service_type",
                "model", "request_count", "audio_seconds", "estimated_cost_usd", "status",
            }
            assert cols == expected, f"unexpected columns: {cols}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_creates_table")


def test_migration_indexes_exist():
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            indexes = {row[1] for row in conn.execute("PRAGMA index_list(api_usage)").fetchall()}
            assert "ix_api_usage_date_service" in indexes, f"missing date_service index; got: {indexes}"
            assert "ix_api_usage_created_at" in indexes, f"missing created_at index; got: {indexes}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_indexes_exist")


def test_migration_version_recorded():
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("20260614_2000_add_api_usage",),
            ).fetchall()
            assert len(rows) == 1, f"expected 1 version row, got {len(rows)}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_version_recorded")


def test_migration_idempotent():
    db_path, tmp = _migration_temp_db()
    try:
        result2 = run_migrations(db_path)
        assert result2.applied == [], f"second run must apply nothing, got: {result2.applied}"
        assert "20260614_2000_add_api_usage" in result2.skipped
    finally:
        tmp.cleanup()
    print("PASS: test_migration_idempotent")


def test_migration_preserves_existing_tables():
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            task_cols = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
            draft_cols = {row[1] for row in conn.execute("PRAGMA table_info(capture_drafts)").fetchall()}
            assert "title" in task_cols, "tasks.title missing after migration"
            assert "raw_text" in draft_cols, "capture_drafts.raw_text missing after migration"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_preserves_existing_tables")


def test_schema_no_private_fields():
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(api_usage)").fetchall()}
            forbidden = {
                "transcript", "task_text", "api_key", "authorization",
                "payload", "telegram_user_id", "user_id", "request_body",
            }
            present = cols & forbidden
            assert not present, f"forbidden private fields found in schema: {present}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_schema_no_private_fields")


# ─── ORM / service tests (async) ──────────────────────────────────────────────


async def test_successful_stt_record():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 14, 10, 0, 0, tzinfo=timezone.utc)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=4.5,
                estimated_cost_usd=0.0001,
                occurred_at=ts,
            )
            await session.commit()

        assert row.id is not None
        assert row.provider == "openrouter"
        assert row.service_type == "stt"
        assert row.model == "openai/whisper-large-v3"
        assert row.audio_seconds == 4.5
        assert abs(row.estimated_cost_usd - 0.0001) < 1e-9
        assert row.status == "success"
        assert row.usage_date == date(2026, 6, 14)
        assert row.request_count == 1
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_successful_stt_record")


async def test_llm_record_with_zero_audio():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record(
                provider="openrouter",
                service_type="llm",
                model="openai/gpt-4o",
                audio_seconds=0.0,
                estimated_cost_usd=0.002,
                status="success",
            )
            await session.commit()
        assert row.service_type == "llm"
        assert row.audio_seconds == 0.0
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_llm_record_with_zero_audio")


async def test_usage_date_from_occurred_at():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 10, 23, 59, 0, tzinfo=timezone.utc)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        assert row.usage_date == date(2026, 6, 10)
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_from_occurred_at")


async def test_append_only_multiple_records():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            for i in range(1, 4):
                await svc.record_stt(
                    provider="openrouter",
                    model="openai/whisper-large-v3",
                    audio_seconds=float(i),
                )
            await session.commit()
        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT audio_seconds FROM api_usage ORDER BY id").fetchall()
            assert len(rows) == 3, f"expected 3 separate rows, got {len(rows)}"
            assert [r[0] for r in rows] == [1.0, 2.0, 3.0]
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_append_only_multiple_records")


async def test_flush_without_commit_not_persisted():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
            )
            assert row.id is not None, "flush must assign id within session"
            # No commit — session.close() on exit triggers rollback

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
            assert count == 0, f"expected 0 rows after no-commit session, got {count}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_flush_without_commit_not_persisted")


async def test_rollback_removes_record():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
            )
            await session.rollback()

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
            assert count == 0, f"expected 0 rows after rollback, got {count}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_rollback_removes_record")


async def test_external_commit_persists_record():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=3.0,
            )
            await session.commit()

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT audio_seconds FROM api_usage").fetchall()
            assert len(rows) == 1
            assert rows[0][0] == 3.0
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_external_commit_persists_record")


# ─── Validation tests (async, no DB needed) ───────────────────────────────────


async def test_negative_audio_seconds_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", audio_seconds=-1.0,
        )
    )
    print("PASS: test_negative_audio_seconds_rejected")


async def test_negative_cost_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", estimated_cost_usd=-0.01,
        )
    )
    print("PASS: test_negative_cost_rejected")


async def test_zero_request_count_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", request_count=0,
        )
    )
    print("PASS: test_zero_request_count_rejected")


async def test_empty_provider_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="", service_type="stt",
            model="openai/whisper-large-v3",
        )
    )
    print("PASS: test_empty_provider_rejected")


async def test_empty_service_type_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="",
            model="openai/whisper-large-v3",
        )
    )
    print("PASS: test_empty_service_type_rejected")


async def test_empty_model_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="",
        )
    )
    print("PASS: test_empty_model_rejected")


async def test_unknown_status_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", status="pending",
        )
    )
    print("PASS: test_unknown_status_rejected")


async def test_unknown_service_type_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="tts",
            model="openai/whisper-large-v3",
        )
    )
    print("PASS: test_unknown_service_type_rejected")


# ─── Daily aggregation test ────────────────────────────────────────────────────


async def test_daily_aggregation():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts_today = datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
        ts_yesterday = ts_today - timedelta(days=1)

        async with maker() as session:
            svc = ApiUsageService(session)
            await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=3.0,
                estimated_cost_usd=0.0001,
                occurred_at=ts_today,
            )
            await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=5.0,
                estimated_cost_usd=0.0002,
                occurred_at=ts_today + timedelta(hours=1),
            )
            await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=10.0,
                estimated_cost_usd=0.0005,
                occurred_at=ts_yesterday,
            )
            await session.commit()

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS rows,
                    SUM(request_count) AS total_requests,
                    SUM(audio_seconds) AS total_seconds,
                    SUM(estimated_cost_usd) AS total_cost
                FROM api_usage
                WHERE usage_date = '2026-06-14'
                """
            ).fetchone()
            assert row[0] == 2, f"expected 2 rows for today, got {row[0]}"
            assert row[1] == 2, f"expected sum(request_count)=2, got {row[1]}"
            assert abs(row[2] - 8.0) < 1e-9, f"expected sum(seconds)=8.0, got {row[2]}"
            assert abs(row[3] - 0.0003) < 1e-9, f"expected sum(cost)=0.0003, got {row[3]}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_daily_aggregation")


# ─── runner ───────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_migration_creates_table,
    test_migration_indexes_exist,
    test_migration_version_recorded,
    test_migration_idempotent,
    test_migration_preserves_existing_tables,
    test_schema_no_private_fields,
]

ASYNC_TESTS = [
    test_successful_stt_record,
    test_llm_record_with_zero_audio,
    test_usage_date_from_occurred_at,
    test_append_only_multiple_records,
    test_flush_without_commit_not_persisted,
    test_rollback_removes_record,
    test_external_commit_persists_record,
    test_negative_audio_seconds_rejected,
    test_negative_cost_rejected,
    test_zero_request_count_rejected,
    test_empty_provider_rejected,
    test_empty_service_type_rejected,
    test_empty_model_rejected,
    test_unknown_status_rejected,
    test_unknown_service_type_rejected,
    test_daily_aggregation,
]


async def main_async() -> None:
    for test_fn in ASYNC_TESTS:
        await test_fn()


def main() -> None:
    for test_fn in SYNC_TESTS:
        test_fn()
    asyncio.run(main_async())
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
