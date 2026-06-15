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
                "input_tokens", "output_tokens",
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


# ─── Stage 18.6-C0: pre-token DB helper and migration tests ──────────────────


def _create_pre_token_db():
    """DB in the state before 20260615_1000_add_token_usage migration."""
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_pre_token_")
    db_path = Path(tmp.name) / "pre_token.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            """
            CREATE TABLE api_usage (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at         DATETIME NOT NULL,
                usage_date         DATE NOT NULL,
                provider           VARCHAR(32) NOT NULL,
                service_type       VARCHAR(16) NOT NULL,
                model              VARCHAR(128) NOT NULL,
                request_count      INTEGER NOT NULL DEFAULT 1,
                audio_seconds      REAL NOT NULL DEFAULT 0.0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                status             VARCHAR(24) NOT NULL DEFAULT 'success'
            )
            """
        )
        conn.execute(
            "INSERT INTO api_usage "
            "(created_at, usage_date, provider, service_type, model, "
            "audio_seconds, estimated_cost_usd, status) VALUES "
            "(datetime('now'), date('now'), 'openrouter', 'stt', "
            "'openai/whisper-large-v3', 5.5, 0.00015, 'success')"
        )
        for v in (
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
            "20260612_0300_add_capture_drafts",
            "20260614_2000_add_api_usage",
        ):
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (?, datetime('now'))",
                (v,),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path, tmp


def test_migration_token_columns_added():
    """Clean-install DB includes input_tokens and output_tokens."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(api_usage)").fetchall()}
            assert "input_tokens" in cols, f"input_tokens missing; cols: {cols}"
            assert "output_tokens" in cols, f"output_tokens missing; cols: {cols}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_token_columns_added")


def test_migration_token_column_defaults():
    """New token columns are NOT NULL with default 0."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
            info = {
                row[1]: row
                for row in conn.execute("PRAGMA table_info(api_usage)").fetchall()
            }
            for col_name in ("input_tokens", "output_tokens"):
                row = info[col_name]
                assert row[3] == 1, (
                    f"{col_name} must be NOT NULL (notnull=1), got {row[3]}"
                )
                assert row[4] == "0", (
                    f"{col_name} default must be '0', got {row[4]!r}"
                )
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_token_column_defaults")


def test_migration_upgrade_preserves_existing_row():
    """Upgrading old DB: existing STT row keeps data; new columns default to 0."""
    db_path, tmp = _create_pre_token_db()
    try:
        run_migrations(db_path)
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            rows = conn.execute(
                "SELECT provider, service_type, model, audio_seconds, "
                "estimated_cost_usd, status, input_tokens, output_tokens "
                "FROM api_usage"
            ).fetchall()
            assert len(rows) == 1, f"expected 1 row after upgrade, got {len(rows)}"
            r = rows[0]
            assert r[0] == "openrouter"
            assert r[1] == "stt"
            assert r[2] == "openai/whisper-large-v3"
            assert abs(r[3] - 5.5) < 1e-9, f"audio_seconds changed: {r[3]}"
            assert abs(r[4] - 0.00015) < 1e-9, f"cost changed: {r[4]}"
            assert r[5] == "success"
            assert r[6] == 0, f"input_tokens must be 0 after upgrade, got {r[6]}"
            assert r[7] == 0, f"output_tokens must be 0 after upgrade, got {r[7]}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_upgrade_preserves_existing_row")


def test_migration_token_version_recorded():
    """Token migration version appears in schema_migrations."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("20260615_1000_add_token_usage",),
            ).fetchall()
            assert len(rows) == 1, f"expected 1 version row, got {len(rows)}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_migration_token_version_recorded")


# ─── Stage 18.6-C0 POST-REVIEW: direct DB constraint tests ──────────────────


def test_db_constraint_sql_has_check():
    """sqlite_master SQL for api_usage contains both CHECK constraints."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None
        try:
            rows = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='api_usage'"
            ).fetchall()
            assert rows, "api_usage not found in sqlite_master"
            combined = " ".join(r[0] or "" for r in rows).upper()
            assert "CHECK" in combined, f"CHECK not found in schema SQL: {combined!r}"
            assert "INPUT_TOKENS" in combined, (
                f"input_tokens CHECK not found in schema SQL: {combined!r}"
            )
            assert "OUTPUT_TOKENS" in combined, (
                f"output_tokens CHECK not found in schema SQL: {combined!r}"
            )
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_db_constraint_sql_has_check")


def test_db_direct_negative_input_tokens_insert_rejected():
    """Direct INSERT bypassing ApiUsageService with negative input_tokens is rejected by SQLite."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "INSERT INTO api_usage "
                    "(created_at, usage_date, provider, service_type, model, "
                    "request_count, audio_seconds, estimated_cost_usd, status, "
                    "input_tokens, output_tokens) "
                    "VALUES (datetime('now'), date('now'), 'test', 'stt', 'test-model', "
                    "1, 0.0, 0.0, 'success', -1, 0)"
                )
                conn.execute("COMMIT")
                raise AssertionError("expected IntegrityError for negative input_tokens INSERT")
            except sqlite3.IntegrityError as e:
                conn.execute("ROLLBACK")
                msg = str(e).lower()
                assert "check" in msg or "constraint" in msg, (
                    f"unexpected error message: {e}"
                )
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_db_direct_negative_input_tokens_insert_rejected")


def test_db_direct_negative_output_tokens_insert_rejected():
    """Direct INSERT bypassing ApiUsageService with negative output_tokens is rejected by SQLite."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None
        try:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "INSERT INTO api_usage "
                    "(created_at, usage_date, provider, service_type, model, "
                    "request_count, audio_seconds, estimated_cost_usd, status, "
                    "input_tokens, output_tokens) "
                    "VALUES (datetime('now'), date('now'), 'test', 'stt', 'test-model', "
                    "1, 0.0, 0.0, 'success', 0, -1)"
                )
                conn.execute("COMMIT")
                raise AssertionError("expected IntegrityError for negative output_tokens INSERT")
            except sqlite3.IntegrityError as e:
                conn.execute("ROLLBACK")
                msg = str(e).lower()
                assert "check" in msg or "constraint" in msg, (
                    f"unexpected error message: {e}"
                )
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_db_direct_negative_output_tokens_insert_rejected")


def test_db_direct_negative_input_tokens_update_rejected():
    """Direct UPDATE: setting input_tokens=-1 is rejected; original row preserved after rollback."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None
        try:
            conn.execute(
                "INSERT INTO api_usage "
                "(created_at, usage_date, provider, service_type, model, "
                "request_count, audio_seconds, estimated_cost_usd, status, "
                "input_tokens, output_tokens) "
                "VALUES (datetime('now'), date('now'), 'test', 'stt', 'test-model', "
                "1, 0.0, 0.0, 'success', 10, 5)"
            )
            row_id = conn.execute("SELECT id FROM api_usage").fetchone()[0]

            conn.execute("BEGIN")
            try:
                conn.execute(
                    "UPDATE api_usage SET input_tokens = -1 WHERE id = ?", (row_id,)
                )
                conn.execute("COMMIT")
                raise AssertionError("expected IntegrityError for negative input_tokens UPDATE")
            except sqlite3.IntegrityError as e:
                conn.execute("ROLLBACK")
                msg = str(e).lower()
                assert "check" in msg or "constraint" in msg, (
                    f"unexpected error message: {e}"
                )

            row = conn.execute(
                "SELECT input_tokens, output_tokens FROM api_usage WHERE id = ?", (row_id,)
            ).fetchone()
            assert row is not None, "row lost after rollback"
            assert row[0] == 10, f"input_tokens changed after failed UPDATE+rollback: {row[0]}"
            assert row[1] == 5, f"output_tokens changed after failed UPDATE+rollback: {row[1]}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_db_direct_negative_input_tokens_update_rejected")


def test_db_direct_negative_output_tokens_update_rejected():
    """Direct UPDATE: setting output_tokens=-1 is rejected; original row preserved after rollback."""
    db_path, tmp = _migration_temp_db()
    try:
        conn = sqlite3.connect(db_path)
        conn.isolation_level = None
        try:
            conn.execute(
                "INSERT INTO api_usage "
                "(created_at, usage_date, provider, service_type, model, "
                "request_count, audio_seconds, estimated_cost_usd, status, "
                "input_tokens, output_tokens) "
                "VALUES (datetime('now'), date('now'), 'test', 'stt', 'test-model', "
                "1, 0.0, 0.0, 'success', 10, 5)"
            )
            row_id = conn.execute("SELECT id FROM api_usage").fetchone()[0]

            conn.execute("BEGIN")
            try:
                conn.execute(
                    "UPDATE api_usage SET output_tokens = -1 WHERE id = ?", (row_id,)
                )
                conn.execute("COMMIT")
                raise AssertionError("expected IntegrityError for negative output_tokens UPDATE")
            except sqlite3.IntegrityError as e:
                conn.execute("ROLLBACK")
                msg = str(e).lower()
                assert "check" in msg or "constraint" in msg, (
                    f"unexpected error message: {e}"
                )

            row = conn.execute(
                "SELECT input_tokens, output_tokens FROM api_usage WHERE id = ?", (row_id,)
            ).fetchone()
            assert row is not None, "row lost after rollback"
            assert row[0] == 10, f"input_tokens changed after failed UPDATE+rollback: {row[0]}"
            assert row[1] == 5, f"output_tokens changed after failed UPDATE+rollback: {row[1]}"
        finally:
            conn.close()
    finally:
        tmp.cleanup()
    print("PASS: test_db_direct_negative_output_tokens_update_rejected")


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
    """23:59 UTC = 04:59 next day Tashkent (UTC+5) → usage_date is next day."""
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
        assert row.usage_date == date(2026, 6, 11), (
            f"23:59 UTC should be 04:59 Tashkent next day, got {row.usage_date}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_from_occurred_at")


async def test_usage_date_tashkent_before_midnight():
    """18:59 UTC = 23:59 Tashkent same day → usage_date stays on June 15."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 15, 18, 59, 0, tzinfo=timezone.utc)
        async with maker() as session:
            row = await ApiUsageService(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        assert row.usage_date == date(2026, 6, 15), (
            f"18:59 UTC = 23:59 Tashkent, expected 2026-06-15, got {row.usage_date}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_tashkent_before_midnight")


async def test_usage_date_tashkent_at_midnight():
    """19:00 UTC = 00:00 Tashkent next day → usage_date advances to June 16."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 15, 19, 0, 0, tzinfo=timezone.utc)
        async with maker() as session:
            row = await ApiUsageService(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        assert row.usage_date == date(2026, 6, 16), (
            f"19:00 UTC = 00:00 Tashkent next day, expected 2026-06-16, got {row.usage_date}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_tashkent_at_midnight")


async def test_usage_date_tashkent_after_midnight():
    """20:30 UTC = 01:30 Tashkent next day → usage_date is June 16."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 15, 20, 30, 0, tzinfo=timezone.utc)
        async with maker() as session:
            row = await ApiUsageService(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        assert row.usage_date == date(2026, 6, 16), (
            f"20:30 UTC = 01:30 Tashkent, expected 2026-06-16, got {row.usage_date}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_tashkent_after_midnight")


async def test_usage_date_cross_offset_aware_timestamp():
    """Aware timestamp with UTC+3 offset: 20:00+03 = 17:00 UTC = 22:00 Tashkent → same day."""
    from zoneinfo import ZoneInfo
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        tz_plus3 = ZoneInfo("Europe/Moscow")
        ts = datetime(2026, 6, 15, 20, 0, 0, tzinfo=tz_plus3)
        async with maker() as session:
            row = await ApiUsageService(session).record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                occurred_at=ts,
            )
            await session.commit()
        assert row.usage_date == date(2026, 6, 15), (
            f"20:00 Moscow (UTC+3) = 17:00 UTC = 22:00 Tashkent, expected 2026-06-15, got {row.usage_date}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_usage_date_cross_offset_aware_timestamp")


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


# ─── Non-finite value tests (Stage 18.6-A1) ──────────────────────────────────


async def test_nan_audio_seconds_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", audio_seconds=float("nan"),
        )
    )
    print("PASS: test_nan_audio_seconds_rejected")


async def test_inf_audio_seconds_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", audio_seconds=float("inf"),
        )
    )
    print("PASS: test_inf_audio_seconds_rejected")


async def test_neg_inf_audio_seconds_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", audio_seconds=float("-inf"),
        )
    )
    print("PASS: test_neg_inf_audio_seconds_rejected")


async def test_finite_positive_audio_seconds_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", audio_seconds=3.14,
    )
    print("PASS: test_finite_positive_audio_seconds_accepted")


async def test_zero_audio_seconds_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", audio_seconds=0.0,
    )
    print("PASS: test_zero_audio_seconds_accepted")


async def test_nan_estimated_cost_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", estimated_cost_usd=float("nan"),
        )
    )
    print("PASS: test_nan_estimated_cost_rejected")


async def test_inf_estimated_cost_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", estimated_cost_usd=float("inf"),
        )
    )
    print("PASS: test_inf_estimated_cost_rejected")


async def test_neg_inf_estimated_cost_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", estimated_cost_usd=float("-inf"),
        )
    )
    print("PASS: test_neg_inf_estimated_cost_rejected")


async def test_finite_positive_estimated_cost_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", estimated_cost_usd=0.0001,
    )
    print("PASS: test_finite_positive_estimated_cost_accepted")


async def test_zero_estimated_cost_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", estimated_cost_usd=0.0,
    )
    print("PASS: test_zero_estimated_cost_accepted")


async def test_non_finite_rejected_no_db_record():
    """Non-finite values that fail validation must not write any row to DB."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        non_finite = [float("nan"), float("inf"), float("-inf")]
        async with maker() as session:
            svc = ApiUsageService(session)
            for bad in non_finite:
                try:
                    await svc.record(
                        provider="openrouter", service_type="stt",
                        model="openai/whisper-large-v3", audio_seconds=bad,
                    )
                except ApiUsageValidationError:
                    pass
                try:
                    await svc.record(
                        provider="openrouter", service_type="stt",
                        model="openai/whisper-large-v3", estimated_cost_usd=bad,
                    )
                except ApiUsageValidationError:
                    pass
            await session.commit()

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
            assert count == 0, f"expected 0 rows after all rejections, got {count}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_non_finite_rejected_no_db_record")


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


# ─── Stage 18.6-C0: token count validation tests ─────────────────────────────


async def test_token_count_zero_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", input_tokens=0, output_tokens=0,
    )
    print("PASS: test_token_count_zero_accepted")


async def test_token_count_positive_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="llm",
        model="openai/gpt-4o-mini", input_tokens=100, output_tokens=50,
    )
    print("PASS: test_token_count_positive_accepted")


async def test_token_count_large_positive_accepted():
    svc = ApiUsageService(_mock_session())
    await svc.record(
        provider="openrouter", service_type="llm",
        model="openai/gpt-4o", input_tokens=1_000_000, output_tokens=500_000,
    )
    print("PASS: test_token_count_large_positive_accepted")


async def test_input_tokens_negative_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", input_tokens=-1,
        )
    )
    print("PASS: test_input_tokens_negative_rejected")


async def test_output_tokens_negative_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", output_tokens=-1,
        )
    )
    print("PASS: test_output_tokens_negative_rejected")


async def test_input_tokens_bool_true_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", input_tokens=True,
        )
    )
    print("PASS: test_input_tokens_bool_true_rejected")


async def test_input_tokens_bool_false_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", input_tokens=False,
        )
    )
    print("PASS: test_input_tokens_bool_false_rejected")


async def test_input_tokens_float_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", input_tokens=1.0,
        )
    )
    print("PASS: test_input_tokens_float_rejected")


async def test_input_tokens_string_rejected():
    svc = ApiUsageService(_mock_session())
    await _expect_validation_error(
        svc.record(
            provider="openrouter", service_type="stt",
            model="openai/whisper-large-v3", input_tokens="1",
        )
    )
    print("PASS: test_input_tokens_string_rejected")


async def test_input_tokens_none_defaults_zero():
    svc = ApiUsageService(_mock_session())
    row = await svc.record(
        provider="openrouter", service_type="stt",
        model="openai/whisper-large-v3", input_tokens=None,
    )
    assert row.input_tokens == 0, f"expected input_tokens=0, got {row.input_tokens}"
    print("PASS: test_input_tokens_none_defaults_zero")


async def test_token_validation_error_no_row():
    """Validation error on tokens must not create any DB row."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            for bad_input, bad_output in [(-5, 0), (0, True), (1.0, 0), (0, "2")]:
                try:
                    await svc.record(
                        provider="openrouter", service_type="stt",
                        model="openai/whisper-large-v3",
                        input_tokens=bad_input, output_tokens=bad_output,
                    )
                except ApiUsageValidationError:
                    pass
            await session.commit()

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
            assert count == 0, f"expected 0 rows after token errors, got {count}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_token_validation_error_no_row")


async def test_token_values_saved_correctly():
    """LLM row with token values persists correctly to DB."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record(
                provider="openrouter",
                service_type="llm",
                model="openai/gpt-4o-mini",
                input_tokens=1024,
                output_tokens=256,
                estimated_cost_usd=0.0005,
            )
            await session.commit()

        assert row.input_tokens == 1024
        assert row.output_tokens == 256
        assert row.audio_seconds == 0.0
        assert row.service_type == "llm"

        await engine.dispose()
        engine = None

        conn = sqlite3.connect(db_path)
        try:
            r = conn.execute(
                "SELECT input_tokens, output_tokens FROM api_usage WHERE id = ?",
                (row.id,),
            ).fetchone()
            assert r is not None
            assert r[0] == 1024, f"expected input_tokens=1024, got {r[0]}"
            assert r[1] == 256, f"expected output_tokens=256, got {r[1]}"
        finally:
            conn.close()
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_token_values_saved_correctly")


# ─── Stage 18.6-C0: STT regression tests ─────────────────────────────────────


async def test_stt_record_has_zero_input_tokens():
    """record_stt() always produces input_tokens=0."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=3.0,
                status="success",
            )
            await session.commit()
        assert row.input_tokens == 0, f"STT input_tokens must be 0, got {row.input_tokens}"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_stt_record_has_zero_input_tokens")


async def test_stt_record_has_zero_output_tokens():
    """record_stt() always produces output_tokens=0 regardless of status."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            svc = ApiUsageService(session)
            row = await svc.record_stt(
                provider="openrouter",
                model="openai/whisper-large-v3",
                audio_seconds=4.5,
                status="error",
            )
            await session.commit()
        assert row.output_tokens == 0, f"STT output_tokens must be 0, got {row.output_tokens}"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_stt_record_has_zero_output_tokens")


# ─── runner ───────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_migration_creates_table,
    test_migration_indexes_exist,
    test_migration_version_recorded,
    test_migration_idempotent,
    test_migration_preserves_existing_tables,
    test_schema_no_private_fields,
    # Stage 18.6-C0: token fields
    test_migration_token_columns_added,
    test_migration_token_column_defaults,
    test_migration_upgrade_preserves_existing_row,
    test_migration_token_version_recorded,
    # Stage 18.6-C0 POST-REVIEW: direct DB constraint tests
    test_db_constraint_sql_has_check,
    test_db_direct_negative_input_tokens_insert_rejected,
    test_db_direct_negative_output_tokens_insert_rejected,
    test_db_direct_negative_input_tokens_update_rejected,
    test_db_direct_negative_output_tokens_update_rejected,
]

ASYNC_TESTS = [
    test_successful_stt_record,
    test_llm_record_with_zero_audio,
    test_usage_date_from_occurred_at,
    test_usage_date_tashkent_before_midnight,
    test_usage_date_tashkent_at_midnight,
    test_usage_date_tashkent_after_midnight,
    test_usage_date_cross_offset_aware_timestamp,
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
    # Stage 18.6-A1: non-finite value tests
    test_nan_audio_seconds_rejected,
    test_inf_audio_seconds_rejected,
    test_neg_inf_audio_seconds_rejected,
    test_finite_positive_audio_seconds_accepted,
    test_zero_audio_seconds_accepted,
    test_nan_estimated_cost_rejected,
    test_inf_estimated_cost_rejected,
    test_neg_inf_estimated_cost_rejected,
    test_finite_positive_estimated_cost_accepted,
    test_zero_estimated_cost_accepted,
    test_non_finite_rejected_no_db_record,
    test_daily_aggregation,
    # Stage 18.6-C0: token count validation
    test_token_count_zero_accepted,
    test_token_count_positive_accepted,
    test_token_count_large_positive_accepted,
    test_input_tokens_negative_rejected,
    test_output_tokens_negative_rejected,
    test_input_tokens_bool_true_rejected,
    test_input_tokens_bool_false_rejected,
    test_input_tokens_float_rejected,
    test_input_tokens_string_rejected,
    test_input_tokens_none_defaults_zero,
    test_token_validation_error_no_row,
    test_token_values_saved_correctly,
    # Stage 18.6-C0: STT regression
    test_stt_record_has_zero_input_tokens,
    test_stt_record_has_zero_output_tokens,
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
