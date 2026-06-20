"""Stage 20.7-A unknown check-in policy: honest state, never fake activity."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import func, select

from app.db.models import ActivityEntry, Checkin
from app.db.test_checkin_text_responses import (
    USER_ID,
    _Message,
    _active,
    _session_ctx,
)
from app.handlers.checkins import try_handle_checkin_text
from app.services.checkin_response_classifier import CheckinResponseClassifier


UNKNOWN_PHRASES = (
    "не помню",
    "не знаю",
    "не помню что делал",
    "bilmiman",
    "nima qilganimni eslolmayman",
    "forgot",
    "i don't remember",
)


def test_unknown_phrase_variants_are_rules_first() -> None:
    classifier = CheckinResponseClassifier()
    for phrase in UNKNOWN_PHRASES:
        assert classifier.classify(phrase).intent == "unknown", phrase


async def test_active_unknown_is_answered_without_activity() -> None:
    settings = SimpleNamespace(allowed_telegram_id=USER_ID)
    for phrase in UNKNOWN_PHRASES:
        async with _session_ctx() as session:
            row = await _active(session)
            handled = await try_handle_checkin_text(
                _Message(phrase), session, settings=settings,
            )
            assert handled is True
            assert row.status == "answered"
            assert row.response_mode == "unknown"
            assert await session.scalar(
                select(func.count()).select_from(ActivityEntry)
            ) == 0


async def test_unknown_without_active_checkin_stays_capture_eligible() -> None:
    settings = SimpleNamespace(allowed_telegram_id=USER_ID)
    async with _session_ctx() as session:
        handled = await try_handle_checkin_text(
            _Message("не помню что делал"), session, settings=settings,
        )
        assert handled is False
        assert await session.scalar(select(func.count()).select_from(Checkin)) == 0
        assert await session.scalar(
            select(func.count()).select_from(ActivityEntry)
        ) == 0


async def main_async() -> None:
    test_unknown_phrase_variants_are_rules_first()
    await test_active_unknown_is_answered_without_activity()
    await test_unknown_without_active_checkin_stays_capture_eligible()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: unknown check-in policy is rules-first and creates no activity")


if __name__ == "__main__":
    main()
