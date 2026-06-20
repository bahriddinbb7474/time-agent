"""Stage 20.6-C voice transcript to confirmed Advisor proposal contract."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.db.models import ActivityEntry, CaptureDraftRecord
from app.db.test_capture_drafts import FakeVoiceMessage, RecordingSTTProvider, _setup_session
from app.handlers.capture import capture_voice_message
from app.services.advisor_presentation_service import AdvisorPresentationResult
from app.services.ai_advisor_provider import AdvisorProposal


async def test_voice_uses_one_llm_call_and_only_shows_proposal() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()
            settings = SimpleNamespace(
                stt_max_duration_sec=60,
                stt_max_file_mb=10,
                stt_daily_request_limit=0,
                stt_daily_seconds_limit=0,
                llm_daily_request_limit=0,
                llm_daily_cost_usd_limit=0.0,
            )
            proposal = AdvisorProposal(
                intent="capture",
                proposal_type="activity",
                title="Работал над отчётом",
                description=None,
                category="work",
                when_text=None,
                target_name=None,
                target_value=None,
                target_unit=None,
                needs_confirmation=True,
                needs_clarification=False,
                user_message="Подтвердить активность?",
                model="fake",
                input_tokens=1,
                output_tokens=1,
                estimated_cost_usd=0.0,
                error=False,
            )
            orchestration = SimpleNamespace(
                validation_result=SimpleNamespace(safe_proposal=proposal),
            )
            presentation = AdvisorPresentationResult(
                text="Подтвердить активность?",
                requires_confirmation=True,
                primary_action="confirm_activity",
                secondary_actions=["cancel"],
                reason_code="activity",
                safe_to_show=True,
            )
            fake_llm = AsyncMock(return_value=orchestration)
            with (
                patch(
                    "app.handlers.capture.advisor_runtime.status",
                    return_value=SimpleNamespace(enabled=True, configuration_ready=True),
                ),
                patch("app.handlers.capture.run_advisor_for_draft", fake_llm),
                patch("app.handlers.capture.format_advisor_result", return_value=presentation),
            ):
                await capture_voice_message(
                    message,
                    session,
                    settings=settings,
                    stt_provider=RecordingSTTProvider("Работал над отчётом"),
                )

            assert fake_llm.await_count == 1
            drafts = list((await session.execute(select(CaptureDraftRecord))).scalars())
            assert len(drafts) == 1
            assert drafts[0].advisor_proposal_json is not None
            assert drafts[0].status == "pending"
            activities = list((await session.execute(select(ActivityEntry))).scalars())
            assert activities == [], "proposal must not create activity before confirmation"
            assert message.answers[0][1] is not None
    finally:
        await engine.dispose()
        tmp.cleanup()


def main() -> None:
    asyncio.run(test_voice_uses_one_llm_call_and_only_shows_proposal())
    print("PASS: voice uses one fake LLM call and waits for owner confirmation")


if __name__ == "__main__":
    main()
