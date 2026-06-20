"""Stage 20.6-D controlled text/voice production smoke contract (local fakes only)."""
from __future__ import annotations

import asyncio
import inspect

from app.db.test_advisor_capture_service import (
    test_advisor_callback_confirm_activity_creates_only_after_confirmation,
)
from app.db.test_capture_drafts import (
    test_voice_fake_stt_fails_closed_without_advisor,
)
from app.db.test_checkin_accounting_integration import (
    test_answers_are_readable_without_fake_activity,
)
from app.db.test_stage20_6_free_text_boundary import main_async as verify_text_boundary
from app.db.test_voice_llm_proposal import (
    test_voice_uses_one_llm_call_and_only_shows_proposal,
)
from app.handlers import capture
from app.services import api_usage_service


def test_private_voice_text_is_not_logged_or_added_to_api_usage() -> None:
    capture_source = inspect.getsource(capture)
    usage_source = inspect.getsource(api_usage_service)
    assert "log.info" not in capture_source
    assert "transcript=" not in usage_source
    assert "raw_text=" not in usage_source
    assert "prompt=" not in usage_source
    assert "response_text=" not in usage_source


async def main_async() -> None:
    await verify_text_boundary()
    await test_voice_fake_stt_fails_closed_without_advisor()
    await test_voice_uses_one_llm_call_and_only_shows_proposal()
    await test_advisor_callback_confirm_activity_creates_only_after_confirmation()
    await test_answers_are_readable_without_fake_activity()
    test_private_voice_text_is_not_logged_or_added_to_api_usage()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: Stage 20.6 text/voice smoke contract (fake providers only)")


if __name__ == "__main__":
    main()
