"""Stage 20-FINAL Block 2 confirmed check-in fact proposal tests."""
from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import now_tz
from app.db.models import ActivityEntry, Base, CaptureDraftRecord
from app.handlers.capture import advisor_capture_callback, capture_text_message
from app.services.advisor_presentation_service import AdvisorPresentationResult
from app.services.advisor_capture_service import _enforce_checkin_fact_intent
from app.services.advisor_orchestrator import AdvisorOrchestrationResult
from app.services.advisor_proposal_validator import validate_advisor_proposal
from app.services.ai_advisor_provider import AdvisorProposal
from app.services.daily_control_service import CheckinService

USER_ID = 123456789
CHAT_ID = 555


class _Message:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=USER_ID)
        self.chat = SimpleNamespace(id=CHAT_ID)
        self.answers: list[tuple[str, object]] = []

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))


class _CallbackMessage:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(id=CHAT_ID)
        self.answers: list[str] = []

    async def answer(self, text):
        self.answers.append(text)

    async def edit_reply_markup(self, *, reply_markup=None):
        return None


class _Callback:
    def __init__(self, action: str) -> None:
        self.data = f"advisor_capture:{action}"
        self.from_user = SimpleNamespace(id=USER_ID)
        self.message = _CallbackMessage()
        self.bot = None
        self.answers = []

    async def answer(self, text=None, *, show_alert=None):
        self.answers.append((text, show_alert))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_fact_proposal_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'fact.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def _active_checkin(session):
    now = now_tz()
    return await CheckinService(session).create(
        user_id=USER_ID,
        window_start=now - timedelta(hours=2),
        window_end=now,
        prompted_at=now - timedelta(minutes=5),
        status="sent",
    )


def _proposal(*, title="Работал над Time-Agent", category="ai_projects"):
    return AdvisorProposal(
        intent="checkin_fact",
        proposal_type="activity",
        title=title,
        description=None,
        category=category,
        when_text=None,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=True,
        needs_clarification=False,
        user_message="Подтвердить факт?",
        model="fake",
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=0.0,
    )


async def _show_proposal(session, message: _Message, proposal) -> AsyncMock:
    orchestration = SimpleNamespace(
        validation_result=SimpleNamespace(safe_proposal=proposal),
    )
    presentation = AdvisorPresentationResult(
        text="Подтвердить факт?",
        requires_confirmation=True,
        primary_action="confirm_activity",
        secondary_actions=["cancel"],
        reason_code="activity",
        safe_to_show=True,
    )
    fake_llm = AsyncMock(return_value=orchestration)
    settings = SimpleNamespace(allowed_telegram_id=USER_ID)
    with (
        patch(
            "app.handlers.capture.advisor_runtime.status",
            return_value=SimpleNamespace(enabled=True, configuration_ready=True),
        ),
        patch("app.handlers.capture.run_advisor_for_draft", fake_llm),
        patch(
            "app.handlers.capture.format_advisor_result",
            return_value=presentation,
        ),
    ):
        await capture_text_message(message, session, settings=settings)
    return fake_llm


async def test_free_text_creates_private_proposal_then_confirmed_fact_once() -> None:
    async with _session_ctx() as session:
        checkin = await _active_checkin(session)
        message = _Message("Работал над Time-Agent")
        fake_llm = await _show_proposal(session, message, _proposal())

        draft = (await session.execute(select(CaptureDraftRecord))).scalar_one()
        metadata = json.loads(draft.advisor_proposal_json)
        assert fake_llm.await_count == 1
        assert draft.status == "pending"
        assert draft.raw_text == "[private advisor input]"
        assert draft.transcript is None
        assert metadata["checkin_id"] == checkin.id
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0

        session.expunge(draft)
        await advisor_capture_callback(_Callback("confirm_activity"), session, None)
        entry = (await session.execute(select(ActivityEntry))).scalar_one()
        assert entry.category == "ai_projects"
        assert entry.source == "checkin_llm"
        assert entry.owner_confirmed is True
        assert entry.waste_marked_by_owner is False
        await session.refresh(checkin)
        assert checkin.status == "answered"

        await advisor_capture_callback(_Callback("confirm_activity"), session, None)
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 1


async def test_cancel_writes_nothing() -> None:
    async with _session_ctx() as session:
        await _active_checkin(session)
        await _show_proposal(session, _Message("Отдыхал"), _proposal(category="entertainment"))
        await advisor_capture_callback(_Callback("cancel"), session, None)
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0


async def test_disabled_llm_fails_closed() -> None:
    async with _session_ctx() as session:
        await _active_checkin(session)
        message = _Message("Работал над проектом")
        fake_llm = AsyncMock()
        with (
            patch(
                "app.handlers.capture.advisor_runtime.status",
                return_value=SimpleNamespace(
                    enabled=False,
                    configuration_ready=False,
                ),
            ),
            patch("app.handlers.capture.run_advisor_for_draft", fake_llm),
        ):
            await capture_text_message(
                message,
                session,
                settings=SimpleNamespace(allowed_telegram_id=USER_ID),
            )
        assert fake_llm.await_count == 0
        assert "Ничего не сохранено" in message.answers[-1][0]
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0
        assert await session.scalar(select(func.count(CaptureDraftRecord.id))) == 0


async def test_unknown_stays_rules_first_without_llm_or_activity() -> None:
    async with _session_ctx() as session:
        checkin = await _active_checkin(session)
        fake_llm = AsyncMock()
        with patch("app.handlers.capture.run_advisor_for_draft", fake_llm):
            await capture_text_message(
                _Message("не помню"),
                session,
                settings=SimpleNamespace(allowed_telegram_id=USER_ID),
            )
        await session.refresh(checkin)
        assert checkin.status == "answered"
        assert checkin.response_mode == "unknown"
        assert fake_llm.await_count == 0
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0


async def test_waste_requires_explicit_text_and_confirmation() -> None:
    async with _session_ctx() as session:
        await _active_checkin(session)
        await _show_proposal(
            session,
            _Message("Потерял время впустую"),
            _proposal(title="Потерянное время", category="waste"),
        )
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0
        await advisor_capture_callback(_Callback("confirm_activity"), session, None)
        entry = (await session.execute(select(ActivityEntry))).scalar_one()
        assert entry.category == "waste"
        assert entry.owner_confirmed is True
        assert entry.waste_marked_by_owner is True


async def test_waste_proposal_without_explicit_owner_text_is_rejected() -> None:
    async with _session_ctx() as session:
        await _active_checkin(session)
        await _show_proposal(
            session,
            _Message("Отдыхал"),
            _proposal(title="Отдых", category="waste"),
        )
        await advisor_capture_callback(_Callback("confirm_activity"), session, None)
        assert await session.scalar(select(func.count(ActivityEntry.id))) == 0
        draft = (await session.execute(select(CaptureDraftRecord))).scalar_one()
        assert draft.status == "cancelled"


async def test_checkin_advisor_guard_rejects_non_activity_and_implicit_waste() -> None:
    for text, proposal in (
        (
            "Работал",
            replace(
                _proposal(title="Новая задача", category="work"),
                proposal_type="task",
            ),
        ),
        ("Отдыхал", _proposal(title="Отдых", category="waste")),
    ):
        validation = await validate_advisor_proposal(proposal, now_dt=now_tz())
        result = AdvisorOrchestrationResult(
            used_advisor=True,
            blocked_by_limit=False,
            provider_error=False,
            validation_result=validation,
            user_message=validation.user_message,
            reason_code="ok",
        )
        draft = SimpleNamespace(advisor_intent="checkin_fact", text=text)
        guarded = await _enforce_checkin_fact_intent(
            draft,
            result,
            now_dt=now_tz(),
        )
        assert guarded.validation_result.safe_proposal.proposal_type == "clarification"


async def main_async() -> None:
    await test_free_text_creates_private_proposal_then_confirmed_fact_once()
    await test_cancel_writes_nothing()
    await test_disabled_llm_fails_closed()
    await test_unknown_stays_rules_first_without_llm_or_activity()
    await test_waste_requires_explicit_text_and_confirmation()
    await test_waste_proposal_without_explicit_owner_text_is_rejected()
    await test_checkin_advisor_guard_rejects_non_activity_and_implicit_waste()


if __name__ == "__main__":
    asyncio.run(main_async())
    print("PASS: check-in facts require private confirmed LLM proposals")
