"""
Stage 19.7-D — Advisor capture service tests.

Verifies:
- advisor_needed() returns False for ordinary high-confidence capture
- advisor_needed() returns True for help/settings/unknown intents
- advisor_needed() returns True when needs_clarification=True
- create_pending_draft() stores advisor_proposal_json
- old create_pending_draft() callers work without advisor_proposal_json
- build_safe_advisor_proposal_json() excludes prompt/response/transcript/api_key
- disabled provider returns safe result
- fake provider returns used_advisor=True result
- gate blocked returns safe result
- one run = max one provider call

No real HTTP, no real LLM, no production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_advisor_capture_service.py
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import Base, CaptureDraftRecord
from app.services.advisor_capture_service import (
    advisor_needed,
    build_safe_advisor_proposal_json,
    run_advisor_for_draft,
)
from app.services.advisor_usage_gate import LlmGateResult
from app.services.ai_advisor_provider import (
    AdvisorProposal,
    FakeAIAdvisorProvider,
)
from app.services.api_limit_service import ApiLimitDecision
from app.services.capture_draft_service import CaptureDraftService
from app.services.capture_router_service import (
    CAPTURE_KIND_BOSS,
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureDraft,
)


CHAT_ID = 555
USER_ID = 123456789

_NOW_DT = now_tz().replace(hour=12, minute=0, second=0, microsecond=0)


def _settings(*, advisor_provider: str = "disabled") -> SimpleNamespace:
    return SimpleNamespace(
        advisor_provider=advisor_provider,
        openrouter_api_key="test-key-not-real",
        openrouter_advisor_model="openai/gpt-4o-mini",
        llm_daily_request_limit=0,
        llm_daily_cost_usd_limit=0.0,
    )


async def _setup_session():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_advisor_capture_")
    db_path = Path(tmp.name) / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        echo=False,
        future=True,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return tmp, engine, Session


def _proposal(
    *,
    proposal_type: str = "later",
    title: str | None = "Тест",
    needs_confirmation: bool = True,
) -> AdvisorProposal:
    return AdvisorProposal(
        intent="capture",
        proposal_type=proposal_type,
        title=title,
        description="описание",
        category="personal",
        when_text=None,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=needs_confirmation,
        needs_clarification=False,
        user_message="Тест.",
        model="fake",
        input_tokens=10,
        output_tokens=20,
        estimated_cost_usd=0.0,
        error=False,
    )


# ── advisor_needed tests ─────────────────────────────────────────────────────


def test_advisor_needed_false_for_high_confidence_capture():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Купить молоко", confidence=1.0,
                         reason_code="rules_later", advisor_intent="capture")
    assert advisor_needed(draft) is False
    print("PASS: test_advisor_needed_false_for_high_confidence_capture")


def test_advisor_needed_false_for_rules_boss():
    draft = CaptureDraft(kind=CAPTURE_KIND_BOSS, text="Boss: отчёт", confidence=1.0,
                         reason_code="rules_boss", advisor_intent="capture")
    assert advisor_needed(draft) is False
    print("PASS: test_advisor_needed_false_for_rules_boss")


def test_advisor_needed_false_for_rules_task():
    draft = CaptureDraft(kind=CAPTURE_KIND_TASK, text="personal Задача", confidence=1.0,
                         reason_code="rules_task", advisor_intent="capture")
    assert advisor_needed(draft) is False
    print("PASS: test_advisor_needed_false_for_rules_task")


def test_advisor_needed_true_for_help():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Как пользоваться", confidence=1.0,
                         reason_code="rules_help", advisor_intent="help")
    assert advisor_needed(draft) is True
    print("PASS: test_advisor_needed_true_for_help")


def test_advisor_needed_true_for_settings():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Измени цель", confidence=1.0,
                         reason_code="rules_settings", advisor_intent="settings")
    assert advisor_needed(draft) is True
    print("PASS: test_advisor_needed_true_for_settings")


def test_advisor_needed_true_for_unknown():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="аб", confidence=0.4,
                         reason_code="rules_unknown", advisor_intent="unknown",
                         needs_clarification=True)
    assert advisor_needed(draft) is True
    print("PASS: test_advisor_needed_true_for_unknown")


def test_advisor_needed_true_for_needs_clarification():
    draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="...", confidence=0.4,
                         reason_code="rules_unknown", advisor_intent="capture",
                         needs_clarification=True)
    assert advisor_needed(draft) is True
    print("PASS: test_advisor_needed_true_for_needs_clarification")


# ── build_safe_advisor_proposal_json tests ───────────────────────────────────


def test_safe_json_contains_only_allowed_keys():
    p = _proposal()
    raw = build_safe_advisor_proposal_json(p)
    data = json.loads(raw)
    allowed = {
        "proposal_type", "title", "description", "category", "when_text",
        "target_name", "target_value", "target_unit",
        "needs_confirmation", "needs_clarification", "user_message",
    }
    assert set(data.keys()) == allowed, f"unexpected keys: {set(data.keys()) - allowed}"
    print("PASS: test_safe_json_contains_only_allowed_keys")


def test_safe_json_excludes_forbidden_fields():
    p = _proposal()
    raw = build_safe_advisor_proposal_json(p)
    forbidden = ["prompt", "response", "transcript", "api_key", "raw_text",
                 "system_prompt", "model", "input_tokens", "output_tokens",
                 "estimated_cost_usd", "error", "intent"]
    data = json.loads(raw)
    for f in forbidden:
        assert f not in data, f"forbidden field {f!r} found in safe json"
    print("PASS: test_safe_json_excludes_forbidden_fields")


def test_safe_json_roundtrips_values():
    p = _proposal(proposal_type="task", title="Задача")
    raw = build_safe_advisor_proposal_json(p)
    data = json.loads(raw)
    assert data["proposal_type"] == "task"
    assert data["title"] == "Задача"
    assert data["needs_confirmation"] is True
    print("PASS: test_safe_json_roundtrips_values")


# ── create_pending_draft with advisor_proposal_json ──────────────────────────


async def test_create_draft_with_advisor_json():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Тест")
            proposal_json = '{"proposal_type":"later","title":"Тест"}'
            record = await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=draft,
                advisor_proposal_json=proposal_json,
            )
            assert record.advisor_proposal_json == proposal_json
        print("PASS: test_create_draft_with_advisor_json")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_create_draft_without_advisor_json_still_works():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Обычный текст")
            record = await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=draft,
            )
            assert record.advisor_proposal_json is None
        print("PASS: test_create_draft_without_advisor_json_still_works")
    finally:
        await engine.dispose()
        tmp.cleanup()


# ── run_advisor_for_draft tests ──────────────────────────────────────────────


async def test_disabled_provider_safe_result():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Помоги",
                                advisor_intent="help", confidence=1.0)
            result = await run_advisor_for_draft(
                draft, session=session, settings=_settings(advisor_provider="disabled"),
                now_dt=_NOW_DT,
            )
            assert result.used_advisor is False
            assert result.reason_code == "advisor_disabled"
        print("PASS: test_disabled_provider_safe_result")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_fake_provider_returns_advisor_result():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Что ты умеешь?",
                                advisor_intent="help", confidence=1.0)
            result = await run_advisor_for_draft(
                draft, session=session, settings=_settings(advisor_provider="fake"),
                now_dt=_NOW_DT,
            )
            assert result.used_advisor is True
            assert result.validation_result is not None
        print("PASS: test_fake_provider_returns_advisor_result")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_gate_blocked_safe_result():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            settings = _settings(advisor_provider="fake")
            settings.llm_daily_request_limit = 1

            from app.services.api_usage_service import ApiUsageService
            await ApiUsageService(session).record_llm(
                provider="fake", model="openai/gpt-4o-mini",
                input_tokens=0, output_tokens=0,
                estimated_cost_usd=0.0, status="success",
            )
            await session.commit()

            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Помоги",
                                advisor_intent="help", confidence=1.0)
            result = await run_advisor_for_draft(
                draft, session=session, settings=settings, now_dt=_NOW_DT,
            )
            assert result.blocked_by_limit is True
            assert result.used_advisor is False
        print("PASS: test_gate_blocked_safe_result")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_one_run_max_one_provider_call():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Помоги",
                                advisor_intent="help", confidence=1.0)
            fake_provider = FakeAIAdvisorProvider()
            original_advise = fake_provider.advise
            call_count = 0

            async def _counting_advise(request):
                nonlocal call_count
                call_count += 1
                return await original_advise(request)

            fake_provider.advise = _counting_advise

            from app.services.advisor_orchestrator import AdvisorOrchestrator
            from app.services.advisor_usage_gate import AdvisorUsageGate

            settings = _settings(advisor_provider="fake")
            gate = AdvisorUsageGate(session, settings)
            orch = AdvisorOrchestrator(
                provider=fake_provider, gate=gate,
                provider_name="fake", model_name="openai/gpt-4o-mini",
            )
            await orch.run(
                __import__("app.services.ai_advisor_provider", fromlist=["AdvisorRequest"]).AdvisorRequest(
                    text="Помоги", advisor_intent="help", confidence=1.0,
                ),
                now_dt=_NOW_DT,
            )
            assert call_count == 1, f"provider called {call_count} times, expected 1"
        print("PASS: test_one_run_max_one_provider_call")
    finally:
        await engine.dispose()
        tmp.cleanup()


# ── Runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_advisor_needed_false_for_high_confidence_capture,
    test_advisor_needed_false_for_rules_boss,
    test_advisor_needed_false_for_rules_task,
    test_advisor_needed_true_for_help,
    test_advisor_needed_true_for_settings,
    test_advisor_needed_true_for_unknown,
    test_advisor_needed_true_for_needs_clarification,
    test_safe_json_contains_only_allowed_keys,
    test_safe_json_excludes_forbidden_fields,
    test_safe_json_roundtrips_values,
]

ASYNC_TESTS = [
    test_create_draft_with_advisor_json,
    test_create_draft_without_advisor_json_still_works,
    test_disabled_provider_safe_result,
    test_fake_provider_returns_advisor_result,
    test_gate_blocked_safe_result,
    test_one_run_max_one_provider_call,
]


async def main_async() -> None:
    for fn in ASYNC_TESTS:
        await fn()


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    asyncio.run(main_async())
    print(f"\nALL {len(SYNC_TESTS) + len(ASYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
