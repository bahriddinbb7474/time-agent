"""
Stage 19.3 — AdvisorUsageGate tests.

Verifies:
- check() calls check_llm() before any provider call
- blocked path writes a limit_exceeded row and returns allowed=False
- allowed path writes no row at check time and returns allowed=True
- record_success() writes service_type="llm", status="success"
- record_error() writes service_type="llm", status="error"
- no prompt/text/transcript/response params accepted anywhere in the gate

No real LLM provider, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_advisor_usage_gate.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.migration_runner import run_migrations
from app.db.models import ApiUsageRecord, Base
from app.services.advisor_usage_gate import AdvisorUsageGate, LlmGateResult
from app.services.api_limit_service import ApiLimitDecision
from app.services.api_usage_service import ApiUsageService


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(llm_request: int = 0, llm_cost: float = 0.0) -> object:
    return SimpleNamespace(
        llm_daily_request_limit=llm_request,
        llm_daily_cost_usd_limit=llm_cost,
        stt_daily_request_limit=0,
        stt_daily_seconds_limit=0.0,
    )


def _migration_temp_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_gate_")
    db_path = Path(tmp.name) / "gate_test.db"
    run_migrations(db_path)
    return db_path, tmp


async def _make_engine(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


_PROVIDER = "openrouter"
_MODEL = "openai/gpt-4o-mini"
_TODAY = date(2026, 6, 17)
_TODAY_TS = datetime(2026, 6, 17, 9, 0, 0, tzinfo=timezone.utc)


# ── Sync tests: signature safety ──────────────────────────────────────────────


def test_gate_result_has_allowed_and_decision_fields():
    decision = ApiLimitDecision(
        allowed=True, reason=None, limit_name=None, current_value=0, limit_value=0
    )
    result = LlmGateResult(allowed=True, decision=decision)
    assert result.allowed is True
    assert result.decision is decision
    print("PASS: test_gate_result_has_allowed_and_decision_fields")


def test_gate_check_signature_no_private_params():
    sig = inspect.signature(AdvisorUsageGate.check)
    params = set(sig.parameters.keys())
    forbidden = {
        "prompt", "text", "response", "transcript",
        "task_text", "user_text", "raw_payload", "message",
    }
    present = params & forbidden
    assert not present, f"check() must not accept private params; found: {present}"
    print("PASS: test_gate_check_signature_no_private_params")


def test_gate_record_success_signature_no_private_params():
    sig = inspect.signature(AdvisorUsageGate.record_success)
    params = set(sig.parameters.keys())
    forbidden = {
        "prompt", "text", "response", "transcript",
        "task_text", "user_text", "raw_payload", "message",
    }
    present = params & forbidden
    assert not present, f"record_success() must not accept private params; found: {present}"
    print("PASS: test_gate_record_success_signature_no_private_params")


def test_gate_record_error_signature_no_private_params():
    sig = inspect.signature(AdvisorUsageGate.record_error)
    params = set(sig.parameters.keys())
    forbidden = {
        "prompt", "text", "response", "transcript",
        "task_text", "user_text", "raw_payload", "message",
    }
    present = params & forbidden
    assert not present, f"record_error() must not accept private params; found: {present}"
    print("PASS: test_gate_record_error_signature_no_private_params")


def test_gate_record_success_has_expected_params():
    sig = inspect.signature(AdvisorUsageGate.record_success)
    params = set(sig.parameters.keys())
    required = {"self", "provider", "model"}
    optional = {"input_tokens", "output_tokens", "estimated_cost_usd"}
    missing_req = required - params
    missing_opt = optional - params
    assert not missing_req, f"record_success() missing required params: {missing_req}"
    assert not missing_opt, f"record_success() missing optional params: {missing_opt}"
    print("PASS: test_gate_record_success_has_expected_params")


# ── Async tests: DB-backed behaviour ──────────────────────────────────────────


async def test_gate_allowed_when_no_request_limit():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg(llm_request=0))
            result = await gate.check(provider=_PROVIDER, model=_MODEL, usage_date=_TODAY)
            await session.commit()
        assert result.allowed is True, f"expected allowed, got {result.allowed}"
        assert result.decision.allowed is True
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_allowed_when_no_request_limit")


async def test_gate_blocked_when_request_limit_reached():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            # Seed one existing LLM request today
            await ApiUsageService(session).record_llm(
                provider=_PROVIDER, model=_MODEL, occurred_at=_TODAY_TS,
            )
            await session.commit()
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg(llm_request=1))
            result = await gate.check(provider=_PROVIDER, model=_MODEL, usage_date=_TODAY)
            await session.commit()
        assert result.allowed is False, "expected blocked when limit reached"
        assert result.decision.allowed is False
        assert result.decision.reason is not None
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_blocked_when_request_limit_reached")


async def test_gate_blocked_records_limit_exceeded_row():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            await ApiUsageService(session).record_llm(
                provider=_PROVIDER, model=_MODEL, occurred_at=_TODAY_TS,
            )
            await session.commit()
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg(llm_request=1))
            await gate.check(provider=_PROVIDER, model=_MODEL, usage_date=_TODAY)
            await session.commit()
        async with maker() as session:
            rows = (
                await session.execute(
                    select(ApiUsageRecord).where(
                        ApiUsageRecord.status == "limit_exceeded"
                    )
                )
            ).scalars().all()
        assert len(rows) == 1, f"expected 1 limit_exceeded row, got {len(rows)}"
        assert rows[0].service_type == "llm"
        assert rows[0].request_count == 0
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_blocked_records_limit_exceeded_row")


async def test_gate_allowed_does_not_write_row_at_check_time():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg(llm_request=0))
            result = await gate.check(provider=_PROVIDER, model=_MODEL, usage_date=_TODAY)
            await session.commit()
        assert result.allowed is True
        # Caller must call record_success() after the provider responds — not before
        async with maker() as session:
            rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
        assert len(rows) == 0, f"expected 0 rows after allowed check, got {len(rows)}"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_allowed_does_not_write_row_at_check_time")


async def test_gate_record_success_writes_llm_success_row():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg())
            await gate.record_success(
                provider=_PROVIDER,
                model=_MODEL,
                input_tokens=200,
                output_tokens=80,
                estimated_cost_usd=0.0004,
            )
            await session.commit()
        async with maker() as session:
            rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.service_type == "llm", f"got {row.service_type!r}"
        assert row.status == "success", f"got {row.status!r}"
        assert row.input_tokens == 200
        assert row.output_tokens == 80
        assert abs(row.estimated_cost_usd - 0.0004) < 1e-9
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_record_success_writes_llm_success_row")


async def test_gate_record_error_writes_llm_error_row():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg())
            await gate.record_error(provider=_PROVIDER, model=_MODEL)
            await session.commit()
        async with maker() as session:
            rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.service_type == "llm", f"got {row.service_type!r}"
        assert row.status == "error", f"got {row.status!r}"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_record_error_writes_llm_error_row")


async def test_gate_full_allowed_flow():
    """check() → allowed → record_success() → correct DB state, no limit_exceeded."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            gate = AdvisorUsageGate(session, _cfg(llm_request=5))
            result = await gate.check(provider=_PROVIDER, model=_MODEL, usage_date=_TODAY)
            assert result.allowed is True
            await gate.record_success(
                provider=_PROVIDER,
                model=_MODEL,
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=0.0002,
            )
            await session.commit()
        async with maker() as session:
            rows = (await session.execute(select(ApiUsageRecord))).scalars().all()
        assert len(rows) == 1, f"expected 1 success row, got {len(rows)}"
        assert rows[0].status == "success"
        assert rows[0].service_type == "llm"
        assert rows[0].input_tokens == 100
        assert rows[0].output_tokens == 50
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_gate_full_allowed_flow")


# ── Runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_gate_result_has_allowed_and_decision_fields,
    test_gate_check_signature_no_private_params,
    test_gate_record_success_signature_no_private_params,
    test_gate_record_error_signature_no_private_params,
    test_gate_record_success_has_expected_params,
]

ASYNC_TESTS = [
    test_gate_allowed_when_no_request_limit,
    test_gate_blocked_when_request_limit_reached,
    test_gate_blocked_records_limit_exceeded_row,
    test_gate_allowed_does_not_write_row_at_check_time,
    test_gate_record_success_writes_llm_success_row,
    test_gate_record_error_writes_llm_error_row,
    test_gate_full_allowed_flow,
]


async def main_async() -> None:
    for fn in ASYNC_TESTS:
        await fn()


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    asyncio.run(main_async())
    print("\nALL 12 TESTS PASSED")


if __name__ == "__main__":
    main()
