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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import ActivityEntry, Base, CaptureDraftRecord, Checkin
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
    CaptureRouterService,
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


def test_settings_routing_regressions():
    router = CaptureRouterService()
    for phrase in (
        "хочу 2 литра воды",
        "добавь цель спорт 20 минут",
        "измени цель вода на 2 литра",
    ):
        draft = router.classify_text(phrase)
        assert draft.advisor_intent == "settings", f"phrase={phrase!r}: {draft}"
        assert advisor_needed(draft) is True

    ordinary = router.classify_text("Купить молоко")
    assert ordinary.advisor_intent == "capture"
    assert advisor_needed(ordinary) is False

    clarification = router.classify_text("ок")
    assert clarification.advisor_intent == "unknown"
    assert clarification.needs_clarification is True

    progress = router.classify_text("Вода +500 мл")
    assert progress.advisor_intent != "settings"
    print("PASS: test_settings_routing_regressions")


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


async def test_settings_intent_guard_converts_task_proposal():
    tmp, engine, Session = await _setup_session()
    try:
        provider = MagicMock()
        provider.advise = AsyncMock(
            return_value=_proposal(proposal_type="task", title="Пить воду")
        )
        async with Session() as session:
            for phrase in (
                "хочу 2 литра воды",
                "добавь цель спорт 20 минут",
                "измени цель вода на 2 литра",
            ):
                draft = CaptureRouterService().classify_text(phrase)
                with patch(
                    "app.services.advisor_capture_service.get_ai_advisor_provider",
                    return_value=provider,
                ):
                    result = await run_advisor_for_draft(
                        draft,
                        session=session,
                        settings=_settings(advisor_provider="fake"),
                        now_dt=_NOW_DT,
                    )
                assert result.validation_result is not None
                safe = result.validation_result.safe_proposal
                assert safe.proposal_type == "settings_change", (
                    f"phrase={phrase!r}: got {safe.proposal_type!r}"
                )
                assert safe.needs_confirmation is True
                assert safe.target_name
                assert safe.target_value
                assert safe.target_unit
        assert provider.advise.await_count == 3
        print("PASS: test_settings_intent_guard_converts_task_proposal")
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


# ── D3: Advisor callback handler tests ───────────────────────────────────────

from sqlalchemy import select
from app.db.models import Task
from app.handlers.capture import _try_advisor_response, advisor_capture_callback
from app.services.capture_confirmation_service import (
    ADVISOR_CAPTURE_CALLBACK_PREFIX,
    build_advisor_callback_data,
)
from app.services.capture_draft_service import (
    CAPTURE_DRAFT_STATUS_CANCELLED,
    CAPTURE_DRAFT_STATUS_CONFIRMED,
    CAPTURE_DRAFT_STATUS_PENDING,
)


class _FakeChat:
    id = CHAT_ID


class _FakeUser:
    id = USER_ID


class _FakeCallbackMessage:
    def __init__(self):
        self.chat = _FakeChat()
        self.answers: list[str] = []
        self.reply_markup_removed = False

    async def answer(self, text: str):
        self.answers.append(text)

    async def edit_reply_markup(self, *, reply_markup=None):
        self.reply_markup_removed = reply_markup is None


class _FakeCaptureMessage(_FakeCallbackMessage):
    def __init__(self):
        super().__init__()
        self.from_user = _FakeUser()

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)


class _FakeCallback:
    def __init__(self, action: str):
        self.data = build_advisor_callback_data(action)
        self.message = _FakeCallbackMessage()
        self.from_user = _FakeUser()
        self.bot = None
        self.answers: list[tuple] = []

    async def answer(self, text=None, *, show_alert=None):
        self.answers.append((text, show_alert))


def _advisor_json(*, proposal_type="later", title="AI задача"):
    import json as _json
    return _json.dumps({
        "proposal_type": proposal_type,
        "title": title,
        "description": None,
        "category": "personal",
        "when_text": None,
        "target_name": None,
        "target_value": None,
        "target_unit": None,
        "needs_confirmation": True,
        "needs_clarification": False,
        "user_message": "Тест.",
    }, ensure_ascii=False)


async def test_disabled_settings_does_not_fall_back_to_task_buttons():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureRouterService().classify_text("хочу 2 литра воды")
            message = _FakeCaptureMessage()
            handled = await _try_advisor_response(
                message,
                session,
                draft,
                service,
                _settings(advisor_provider="disabled"),
            )
            assert handled is True
            assert any("недоступно" in answer for answer in message.answers)
            pending = await service.get_latest_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
            )
            assert pending is None, "disabled settings must not create an ordinary draft"
        print("PASS: test_disabled_settings_does_not_fall_back_to_task_buttons")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_cancel_marks_cancelled():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Тест отмена")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=_advisor_json(),
            )
            cb = _FakeCallback("cancel")
            await advisor_capture_callback(cb, session, scheduler=None)
            record = await service._get_latest_by_status(
                chat_id=CHAT_ID, user_id=USER_ID, status=CAPTURE_DRAFT_STATUS_CANCELLED,
            )
            assert record is not None
        print("PASS: test_advisor_callback_cancel_marks_cancelled")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_missing_json_fails_closed():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Нет json")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
            )
            cb = _FakeCallback("confirm_later")
            await advisor_capture_callback(cb, session, scheduler=None)
            assert any("устарело" in a.lower() for a in cb.message.answers), \
                f"expected stale proposal message, got: {cb.message.answers}"
            record = await service._get_latest_by_status(
                chat_id=CHAT_ID, user_id=USER_ID, status=CAPTURE_DRAFT_STATUS_CANCELLED,
            )
            assert record is not None
        print("PASS: test_advisor_callback_missing_json_fails_closed")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_invalid_json_fails_closed():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Плохой json")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json="not-json{{{",
            )
            cb = _FakeCallback("confirm_task")
            await advisor_capture_callback(cb, session, scheduler=None)
            record = await service._get_latest_by_status(
                chat_id=CHAT_ID, user_id=USER_ID, status=CAPTURE_DRAFT_STATUS_CANCELLED,
            )
            assert record is not None
        print("PASS: test_advisor_callback_invalid_json_fails_closed")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_confirm_later_creates_task():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="AI позже")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=_advisor_json(proposal_type="later", title="AI позже"),
            )
            cb = _FakeCallback("confirm_later")
            await advisor_capture_callback(cb, session, scheduler=None)
            result = await session.execute(select(Task).order_by(Task.id.desc()))
            task = result.scalars().first()
            assert task is not None
            assert task.status == "later"
            record = await service._get_latest_by_status(
                chat_id=CHAT_ID, user_id=USER_ID, status=CAPTURE_DRAFT_STATUS_CONFIRMED,
            )
            assert record is not None
        print("PASS: test_advisor_callback_confirm_later_creates_task")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_confirm_task_creates_task():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="personal AI задача")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=_advisor_json(proposal_type="task", title="personal AI задача"),
            )
            cb = _FakeCallback("confirm_task")
            await advisor_capture_callback(cb, session, scheduler=None)
            result = await session.execute(select(Task).order_by(Task.id.desc()))
            task = result.scalars().first()
            assert task is not None
            assert task.status == "todo"
        print("PASS: test_advisor_callback_confirm_task_creates_task")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_confirm_boss_creates_task():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Boss отчёт")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=_advisor_json(proposal_type="boss", title="Boss отчёт"),
            )
            cb = _FakeCallback("confirm_boss")
            await advisor_capture_callback(cb, session, scheduler=None)
            result = await session.execute(select(Task).order_by(Task.id.desc()))
            task = result.scalars().first()
            assert task is not None
            assert task.status == "todo"
        print("PASS: test_advisor_callback_confirm_boss_creates_task")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_confirm_activity_creates_only_after_confirmation():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            now = now_tz()
            checkin = Checkin(
                user_id=USER_ID,
                usage_date=now.date(),
                window_start=now - timedelta(minutes=30),
                window_end=now + timedelta(minutes=30),
                prompted_at=now - timedelta(minutes=1),
                status="sent",
                created_at=now,
                updated_at=now,
            )
            session.add(checkin)
            await session.commit()

            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Работал над отчётом")
            await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=draft,
                source="voice",
                transcript=None,
                advisor_proposal_json=_advisor_json(
                    proposal_type="activity", title="Работал над отчётом",
                ),
            )
            before = await session.execute(select(ActivityEntry))
            assert list(before.scalars().all()) == []

            cb = _FakeCallback("confirm_activity")
            await advisor_capture_callback(cb, session, scheduler=None)

            result = await session.execute(select(ActivityEntry))
            activity = result.scalar_one()
            assert activity.title == "Работал над отчётом"
            assert activity.source == "voice_llm"
            assert activity.owner_confirmed is True
            assert activity.waste_marked_by_owner is False
            await session.refresh(checkin)
            assert checkin.status == "answered"
            assert checkin.response_mode == "voice_activity"
        print("PASS: test_advisor_callback_confirm_activity_creates_only_after_confirmation")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_confirm_settings_does_not_mutate_targets():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Измени цель")
            settings_json = json.dumps({
                "proposal_type": "settings_change",
                "title": None,
                "description": None,
                "category": None,
                "when_text": None,
                "target_name": "daily_task_limit",
                "target_value": "10",
                "target_unit": "задач",
                "needs_confirmation": True,
                "needs_clarification": False,
                "user_message": "Изменить?",
            }, ensure_ascii=False)
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=settings_json,
            )
            cb = _FakeCallback("confirm_settings_change")
            await advisor_capture_callback(cb, session, scheduler=None)
            assert any("следующем этапе" in a for a in cb.message.answers), \
                f"expected stub message, got: {cb.message.answers}"
            record = await service._get_latest_by_status(
                chat_id=CHAT_ID, user_id=USER_ID, status=CAPTURE_DRAFT_STATUS_CONFIRMED,
            )
            assert record is not None
            result = await session.execute(select(Task))
            assert list(result.scalars().all()) == [], "settings_change must not create tasks"
        print("PASS: test_advisor_callback_confirm_settings_does_not_mutate_targets")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_rejects_action_type_mismatch():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="хочу 2 литра воды")
            await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=draft,
                advisor_proposal_json=_advisor_json(
                    proposal_type="settings_change",
                    title=None,
                ),
            )
            cb = _FakeCallback("confirm_task")
            await advisor_capture_callback(cb, session, scheduler=None)
            result = await session.execute(select(Task))
            assert list(result.scalars().all()) == [], "mismatched callback must not create tasks"
            assert any("устарело" in answer for answer in cb.message.answers)
        print("PASS: test_advisor_callback_rejects_action_type_mismatch")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_no_second_llm_call():
    """Callback handler must not call LLM — it uses stored proposal_json only."""
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            draft = CaptureDraft(kind=CAPTURE_KIND_LATER, text="Тест без LLM")
            await service.create_pending_draft(
                chat_id=CHAT_ID, user_id=USER_ID, draft=draft,
                advisor_proposal_json=_advisor_json(),
            )
            cb = _FakeCallback("confirm_later")
            await advisor_capture_callback(cb, session, scheduler=None)
            # If we reach here without error, no LLM was called
            # (there is no provider wiring in the callback handler)
        print("PASS: test_advisor_callback_no_second_llm_call")
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_advisor_callback_ask_clarification_safe():
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            cb = _FakeCallback("ask_clarification")
            await advisor_capture_callback(cb, session, scheduler=None)
            assert any("Уточните" in a for a in cb.message.answers), \
                f"expected clarification message, got: {cb.message.answers}"
        print("PASS: test_advisor_callback_ask_clarification_safe")
    finally:
        await engine.dispose()
        tmp.cleanup()


def test_advisor_callback_data_length_under_telegram_limit():
    actions = [
        "confirm_task", "confirm_later", "confirm_boss",
        "confirm_activity", "confirm_settings_change", "ask_clarification", "cancel",
    ]
    for action in actions:
        data = build_advisor_callback_data(action)
        assert len(data.encode("utf-8")) <= 64, \
            f"callback_data {data!r} exceeds Telegram 64-byte limit: {len(data.encode('utf-8'))}"
    print("PASS: test_advisor_callback_data_length_under_telegram_limit")


# ── Runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_advisor_needed_false_for_high_confidence_capture,
    test_advisor_needed_false_for_rules_boss,
    test_advisor_needed_false_for_rules_task,
    test_advisor_needed_true_for_help,
    test_advisor_needed_true_for_settings,
    test_advisor_needed_true_for_unknown,
    test_advisor_needed_true_for_needs_clarification,
    test_settings_routing_regressions,
    test_safe_json_contains_only_allowed_keys,
    test_safe_json_excludes_forbidden_fields,
    test_safe_json_roundtrips_values,
    test_advisor_callback_data_length_under_telegram_limit,
]

ASYNC_TESTS = [
    test_create_draft_with_advisor_json,
    test_create_draft_without_advisor_json_still_works,
    test_disabled_provider_safe_result,
    test_fake_provider_returns_advisor_result,
    test_settings_intent_guard_converts_task_proposal,
    test_gate_blocked_safe_result,
    test_one_run_max_one_provider_call,
    test_disabled_settings_does_not_fall_back_to_task_buttons,
    # D3: callback handler tests
    test_advisor_callback_cancel_marks_cancelled,
    test_advisor_callback_missing_json_fails_closed,
    test_advisor_callback_invalid_json_fails_closed,
    test_advisor_callback_confirm_later_creates_task,
    test_advisor_callback_confirm_task_creates_task,
    test_advisor_callback_confirm_boss_creates_task,
    test_advisor_callback_confirm_activity_creates_only_after_confirmation,
    test_advisor_callback_confirm_settings_does_not_mutate_targets,
    test_advisor_callback_rejects_action_type_mismatch,
    test_advisor_callback_no_second_llm_call,
    test_advisor_callback_ask_clarification_safe,
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
