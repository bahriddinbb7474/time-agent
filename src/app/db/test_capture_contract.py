"""
Stage 19.1 — Capture/Advisor contract DTO + record_llm tests.

Verifies:
- CaptureDraft has new fields with safe defaults
- classify_text() preserves existing kind values
- reason_code is set correctly per classification path
- advisor_intent defaults to "capture"
- record_llm() writes service_type="llm"
- record_llm() signature has no private-data parameters

No LLM provider is connected. No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_capture_contract.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
from app.services.capture_router_service import (
    CAPTURE_KIND_BOSS,
    CAPTURE_KIND_IGNORE,
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureDraft,
    CaptureRouterService,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _mock_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    return session


def _migration_temp_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_contract_")
    db_path = Path(tmp.name) / "contract.db"
    run_migrations(db_path)
    return db_path, tmp


async def _make_engine(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


# ─── CaptureDraft DTO field tests (sync) ──────────────────────────────────────


def test_capture_draft_new_fields_have_defaults():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Купить молоко")
    assert draft.confidence == 1.0, f"expected 1.0, got {draft.confidence}"
    assert draft.reason_code == "rules", f"expected 'rules', got {draft.reason_code!r}"
    assert draft.needs_clarification is False, f"expected False, got {draft.needs_clarification}"
    assert draft.advisor_intent == "capture", f"expected 'capture', got {draft.advisor_intent!r}"
    print("PASS: test_capture_draft_new_fields_have_defaults")


def test_capture_draft_advisor_intent_default_is_capture():
    draft = CaptureDraft(kind=CAPTURE_KIND_TASK, text="work Созвониться с клиентом")
    assert draft.advisor_intent == "capture"
    print("PASS: test_capture_draft_advisor_intent_default_is_capture")


def test_capture_draft_reason_code_can_be_set():
    draft = CaptureDraft(kind=CAPTURE_KIND_BOSS, text="Шеф: срочно", reason_code="rules_boss")
    assert draft.reason_code == "rules_boss"
    print("PASS: test_capture_draft_reason_code_can_be_set")


def test_capture_draft_backward_compatible_construction():
    # Existing code that passes only kind+text must still work after adding new fields
    d1 = CaptureDraft(kind=CAPTURE_KIND_LATER, text="idea")
    d2 = CaptureDraft(kind=CAPTURE_KIND_TASK, text="work task", category="work", title="task")
    assert d1.kind == CAPTURE_KIND_LATER
    assert d2.category == "work"
    print("PASS: test_capture_draft_backward_compatible_construction")


# ─── classify_text() reason_code tests (sync) ─────────────────────────────────


def test_classify_empty_text_is_ignore_with_rules_ignore():
    draft = CaptureRouterService().classify_text("")
    assert draft.kind == CAPTURE_KIND_IGNORE
    assert draft.reason_code == "rules_ignore", f"got {draft.reason_code!r}"
    print("PASS: test_classify_empty_text_is_ignore_with_rules_ignore")


def test_classify_none_is_ignore_with_rules_ignore():
    draft = CaptureRouterService().classify_text(None)
    assert draft.kind == CAPTURE_KIND_IGNORE
    assert draft.reason_code == "rules_ignore"
    print("PASS: test_classify_none_is_ignore_with_rules_ignore")


def test_classify_slash_command_is_ignore_with_rules_ignore():
    draft = CaptureRouterService().classify_text("/help")
    assert draft.kind == CAPTURE_KIND_IGNORE
    assert draft.reason_code == "rules_ignore"
    print("PASS: test_classify_slash_command_is_ignore_with_rules_ignore")


def test_classify_boss_prefix_returns_boss_kind_and_rules_boss():
    draft = CaptureRouterService().classify_text("boss Отправить отчёт")
    assert draft.kind == CAPTURE_KIND_BOSS, f"expected boss, got {draft.kind!r}"
    assert draft.reason_code == "rules_boss", f"got {draft.reason_code!r}"
    print("PASS: test_classify_boss_prefix_returns_boss_kind_and_rules_boss")


def test_classify_urgent_returns_boss_kind_and_rules_boss():
    draft = CaptureRouterService().classify_text("Срочно позвонить директору")
    assert draft.kind == CAPTURE_KIND_BOSS
    assert draft.reason_code == "rules_boss"
    print("PASS: test_classify_urgent_returns_boss_kind_and_rules_boss")


def test_classify_category_prefix_returns_task_kind_and_rules_task():
    draft = CaptureRouterService().classify_text("work Созвониться")
    assert draft.kind == CAPTURE_KIND_TASK, f"expected task, got {draft.kind!r}"
    assert draft.reason_code == "rules_task", f"got {draft.reason_code!r}"
    print("PASS: test_classify_category_prefix_returns_task_kind_and_rules_task")


def test_classify_plain_text_returns_later_kind_and_rules_later():
    draft = CaptureRouterService().classify_text("Купить молоко")
    assert draft.kind == CAPTURE_KIND_LATER, f"expected later, got {draft.kind!r}"
    assert draft.reason_code == "rules_later", f"got {draft.reason_code!r}"
    print("PASS: test_classify_plain_text_returns_later_kind_and_rules_later")


def test_classify_confidence_always_one_point_zero():
    for text in ["Купить молоко", "work task", "boss срочно", ""]:
        draft = CaptureRouterService().classify_text(text)
        assert draft.confidence == 1.0, (
            f"rules classifier must always return confidence=1.0, got {draft.confidence} for {text!r}"
        )
    print("PASS: test_classify_confidence_always_one_point_zero")


def test_classify_needs_clarification_always_false():
    for text in ["Купить молоко", "work task", "boss срочно", "/cmd", ""]:
        draft = CaptureRouterService().classify_text(text)
        assert draft.needs_clarification is False, (
            f"rules classifier must not set needs_clarification=True, got True for {text!r}"
        )
    print("PASS: test_classify_needs_clarification_always_false")


def test_classify_advisor_intent_always_capture():
    for text in ["Купить молоко", "work task", "boss срочно", "/cmd", ""]:
        draft = CaptureRouterService().classify_text(text)
        assert draft.advisor_intent == "capture", (
            f"Stage 19.1: advisor_intent must default to 'capture', got {draft.advisor_intent!r} for {text!r}"
        )
    print("PASS: test_classify_advisor_intent_always_capture")


# ─── record_llm() signature safety test (sync) ────────────────────────────────


def test_record_llm_signature_has_no_private_params():
    sig = inspect.signature(ApiUsageService.record_llm)
    param_names = set(sig.parameters.keys())
    forbidden = {
        "prompt", "response", "transcript", "task_text",
        "user_text", "raw_payload", "text", "message",
    }
    present = param_names & forbidden
    assert not present, (
        f"record_llm() must not accept private-data params; found: {present}"
    )
    print("PASS: test_record_llm_signature_has_no_private_params")


def test_record_llm_signature_has_expected_params():
    sig = inspect.signature(ApiUsageService.record_llm)
    params = set(sig.parameters.keys())
    required = {"self", "provider", "model"}
    optional = {"input_tokens", "output_tokens", "estimated_cost_usd", "status", "occurred_at"}
    missing_required = required - params
    missing_optional = optional - params
    assert not missing_required, f"record_llm() missing required params: {missing_required}"
    assert not missing_optional, f"record_llm() missing optional params: {missing_optional}"
    print("PASS: test_record_llm_signature_has_expected_params")


# ─── record_llm() DB tests (async) ────────────────────────────────────────────


async def test_record_llm_service_type_is_llm():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            row = await ApiUsageService(session).record_llm(
                provider="openrouter",
                model="openai/gpt-4o-mini",
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=0.0003,
            )
            await session.commit()
        assert row.service_type == "llm", f"expected 'llm', got {row.service_type!r}"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_record_llm_service_type_is_llm")


async def test_record_llm_stores_tokens_and_cost():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            row = await ApiUsageService(session).record_llm(
                provider="openrouter",
                model="openai/gpt-4o-mini",
                input_tokens=512,
                output_tokens=128,
                estimated_cost_usd=0.0007,
                status="success",
            )
            await session.commit()
        assert row.input_tokens == 512, f"expected 512, got {row.input_tokens}"
        assert row.output_tokens == 128, f"expected 128, got {row.output_tokens}"
        assert abs(row.estimated_cost_usd - 0.0007) < 1e-9
        assert row.provider == "openrouter"
        assert row.model == "openai/gpt-4o-mini"
        assert row.status == "success"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_record_llm_stores_tokens_and_cost")


async def test_record_llm_audio_seconds_is_zero():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            row = await ApiUsageService(session).record_llm(
                provider="openrouter",
                model="openai/gpt-4o-mini",
            )
            await session.commit()
        assert row.audio_seconds == 0.0, (
            f"LLM record must have audio_seconds=0.0, got {row.audio_seconds}"
        )
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_record_llm_audio_seconds_is_zero")


async def test_record_llm_appears_in_daily_summary_as_llm():
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        ts = datetime(2026, 6, 17, 10, 0, 0, tzinfo=timezone.utc)
        async with maker() as session:
            svc = ApiUsageService(session)
            await svc.record_llm(
                provider="openrouter",
                model="openai/gpt-4o-mini",
                input_tokens=200,
                output_tokens=100,
                estimated_cost_usd=0.0005,
                occurred_at=ts,
            )
            await session.commit()

        from datetime import date
        from zoneinfo import ZoneInfo
        tashkent_date = ts.astimezone(ZoneInfo("Asia/Tashkent")).date()

        async with maker() as session:
            summary = await ApiUsageService(session).get_daily_summary(tashkent_date)

        assert summary.llm_request_count == 1, (
            f"llm_request_count must be 1, got {summary.llm_request_count}"
        )
        assert summary.llm_input_tokens == 200
        assert summary.llm_output_tokens == 100
        assert summary.stt_request_count == 0, "STT count must not include LLM row"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_record_llm_appears_in_daily_summary_as_llm")


async def test_record_llm_limit_exceeded_via_record():
    """record_limit_exceeded() works for llm service_type."""
    db_path, tmp = _migration_temp_db()
    engine = None
    try:
        engine, maker = await _make_engine(db_path)
        async with maker() as session:
            row = await ApiUsageService(session).record_limit_exceeded(
                provider="openrouter",
                service_type="llm",
                model="openai/gpt-4o-mini",
            )
            await session.commit()
        assert row.service_type == "llm"
        assert row.request_count == 0
        assert row.status == "limit_exceeded"
    finally:
        if engine:
            await engine.dispose()
        tmp.cleanup()
    print("PASS: test_record_llm_limit_exceeded_via_record")


# ─── runner ───────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_capture_draft_new_fields_have_defaults,
    test_capture_draft_advisor_intent_default_is_capture,
    test_capture_draft_reason_code_can_be_set,
    test_capture_draft_backward_compatible_construction,
    test_classify_empty_text_is_ignore_with_rules_ignore,
    test_classify_none_is_ignore_with_rules_ignore,
    test_classify_slash_command_is_ignore_with_rules_ignore,
    test_classify_boss_prefix_returns_boss_kind_and_rules_boss,
    test_classify_urgent_returns_boss_kind_and_rules_boss,
    test_classify_category_prefix_returns_task_kind_and_rules_task,
    test_classify_plain_text_returns_later_kind_and_rules_later,
    test_classify_confidence_always_one_point_zero,
    test_classify_needs_clarification_always_false,
    test_classify_advisor_intent_always_capture,
    test_record_llm_signature_has_no_private_params,
    test_record_llm_signature_has_expected_params,
]

ASYNC_TESTS = [
    test_record_llm_service_type_is_llm,
    test_record_llm_stores_tokens_and_cost,
    test_record_llm_audio_seconds_is_zero,
    test_record_llm_appears_in_daily_summary_as_llm,
    test_record_llm_limit_exceeded_via_record,
]


async def main_async() -> None:
    for fn in ASYNC_TESTS:
        await fn()


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    asyncio.run(main_async())
    print("\nALL 21 TESTS PASSED")


if __name__ == "__main__":
    main()
