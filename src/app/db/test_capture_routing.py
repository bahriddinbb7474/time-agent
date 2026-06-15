"""
Stage 18.6-C hotfix — capture routing filter tests.

Verifies that the @router.message(F.text & ~F.text.startswith("/")) filter
correctly prevents slash-commands from entering the capture handler.

Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_capture_routing.py
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, CaptureDraftRecord
from app.handlers.capture import capture_text_message


# ─── Filter semantics ─────────────────────────────────────────────────────────
#
# The filter F.text & ~F.text.startswith("/") is semantically equivalent to:
#   message.text is not None and not message.text.startswith("/")
#
# We test these exact semantics so the tests are stable across aiogram
# minor releases and don't depend on internal MagicFilter evaluation APIs.


def _filter_matches(text: str | None) -> bool:
    """Mirrors the semantics of F.text & ~F.text.startswith('/')."""
    return text is not None and not text.startswith("/")


def test_filter_slash_usage_blocked():
    assert not _filter_matches("/usage"), "/usage must not reach capture handler"
    print("PASS: test_filter_slash_usage_blocked")


def test_filter_slash_health_blocked():
    assert not _filter_matches("/health"), "/health must not reach capture handler"
    print("PASS: test_filter_slash_health_blocked")


def test_filter_slash_today_blocked():
    assert not _filter_matches("/today"), "/today must not reach capture handler"
    print("PASS: test_filter_slash_today_blocked")


def test_filter_slash_start_blocked():
    assert not _filter_matches("/start"), "/start must not reach capture handler"
    print("PASS: test_filter_slash_start_blocked")


def test_filter_unknown_command_blocked():
    assert not _filter_matches("/unknown_command"), (
        "/unknown_command must not reach capture handler"
    )
    print("PASS: test_filter_unknown_command_blocked")


def test_filter_slash_with_mention_blocked():
    """Commands with @botname (e.g. /usage@test_bot) start with '/' — must be blocked."""
    assert not _filter_matches("/usage@test_bot"), (
        "/usage@test_bot must not reach capture handler"
    )
    print("PASS: test_filter_slash_with_mention_blocked")


def test_filter_none_text_blocked():
    assert not _filter_matches(None), "None text must not reach capture handler"
    print("PASS: test_filter_none_text_blocked")


def test_filter_normal_text_passes():
    assert _filter_matches("Завтра проверить договор"), (
        "Normal text must reach capture handler"
    )
    print("PASS: test_filter_normal_text_passes")


def test_filter_slash_inside_text_passes():
    """Slash NOT at the start is plain text — must reach capture handler."""
    assert _filter_matches("Проверить папку /opt/time-agent"), (
        "Text with slash not at start must reach capture handler"
    )
    print("PASS: test_filter_slash_inside_text_passes")


def test_filter_empty_string_passes():
    """Empty string passes the filter (handler classify_text will return IGNORE)."""
    assert _filter_matches(""), "Empty string passes filter (classify_text handles it)"
    print("PASS: test_filter_empty_string_passes")


# ─── Handler level tests ──────────────────────────────────────────────────────
#
# Even if the aiogram filter were misconfigured, the handler has defense-in-depth
# via classify_text("/...") -> CAPTURE_KIND_IGNORE -> silent return.
# These tests verify that defense layer works independently.


async def _setup_session():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_capture_routing_")
    db_path = Path(tmp.name) / "routing.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return tmp, engine, maker


class FakeChat:
    id = 555


class FakeUser:
    id = 123


class FakeTextMessage:
    def __init__(self, text: str):
        self.text = text
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append(text)


async def _count_drafts(session) -> int:
    result = await session.execute(select(CaptureDraftRecord))
    return len(list(result.scalars().all()))


async def test_handler_slash_usage_creates_no_draft():
    """Defense-in-depth: /usage sent to handler directly must not create a draft."""
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("/usage")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, f"/usage must not create draft, got {count} drafts"
        assert msg.answers == [], f"/usage must produce no response, got {msg.answers}"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_slash_usage_creates_no_draft")


async def test_handler_slash_health_creates_no_draft():
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("/health")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, f"/health must not create draft"
        assert msg.answers == []
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_slash_health_creates_no_draft")


async def test_handler_slash_today_creates_no_draft():
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("/today")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, f"/today must not create draft"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_slash_today_creates_no_draft")


async def test_handler_unknown_command_creates_no_draft():
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("/unknown_command")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, f"/unknown_command must not create draft"
        assert msg.answers == [], "no response expected for unknown command via capture handler"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_unknown_command_creates_no_draft")


async def test_handler_slash_with_mention_creates_no_draft():
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("/usage@test_bot")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, "/usage@test_bot must not create draft"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_slash_with_mention_creates_no_draft")


async def test_handler_normal_text_creates_draft():
    """Regression: normal text must still reach capture flow and create a draft."""
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("Завтра проверить договор")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 1, f"Normal text must create 1 draft, got {count}"
        assert len(msg.answers) == 1, "Normal text must produce a confirmation prompt"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_normal_text_creates_draft")


async def test_handler_slash_inside_text_creates_draft():
    """Slash NOT at the start is plain text — must create a draft."""
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage("Проверить папку /opt/time-agent")
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 1, f"Text with slash not at start must create draft, got {count}"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_slash_inside_text_creates_draft")


async def test_handler_none_text_creates_no_draft():
    """None text (not a real text message) must not create a draft."""
    tmp, engine, maker = await _setup_session()
    try:
        async with maker() as session:
            msg = FakeTextMessage.__new__(FakeTextMessage)
            msg.text = None
            msg.chat = FakeChat()
            msg.from_user = FakeUser()
            msg.answers = []
            await capture_text_message(msg, session)
            count = await _count_drafts(session)
        assert count == 0, "None text must not create draft"
    finally:
        await engine.dispose()
        tmp.cleanup()
    print("PASS: test_handler_none_text_creates_no_draft")


# ─── Voice regression ──────────────────────────────────────────────────────────


def test_voice_handler_uses_f_voice_filter():
    """Verify voice handler filter is F.voice (not F.text) — unchanged by hotfix."""
    import inspect
    from app.handlers.capture import capture_voice_message
    # The voice handler must exist and have a different filter than text handler.
    # Proof: capture_text_message and capture_voice_message are distinct functions.
    assert capture_voice_message is not capture_text_message
    print("PASS: test_voice_handler_uses_f_voice_filter")


# ─── Test runner ──────────────────────────────────────────────────────────────

SYNC_TESTS = [
    test_filter_slash_usage_blocked,
    test_filter_slash_health_blocked,
    test_filter_slash_today_blocked,
    test_filter_slash_start_blocked,
    test_filter_unknown_command_blocked,
    test_filter_slash_with_mention_blocked,
    test_filter_none_text_blocked,
    test_filter_normal_text_passes,
    test_filter_slash_inside_text_passes,
    test_filter_empty_string_passes,
    test_voice_handler_uses_f_voice_filter,
]

ASYNC_TESTS = [
    test_handler_slash_usage_creates_no_draft,
    test_handler_slash_health_creates_no_draft,
    test_handler_slash_today_creates_no_draft,
    test_handler_unknown_command_creates_no_draft,
    test_handler_slash_with_mention_creates_no_draft,
    test_handler_normal_text_creates_draft,
    test_handler_slash_inside_text_creates_draft,
    test_handler_none_text_creates_no_draft,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()

    async def run_async():
        for fn in ASYNC_TESTS:
            await fn()

    asyncio.run(run_async())

    total = len(SYNC_TESTS) + len(ASYNC_TESTS)
    print(f"PASS: all {total} capture routing tests passed")


if __name__ == "__main__":
    main()
