import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.db.models import Base, CaptureDraftRecord, Task
from app.handlers.capture import capture_confirmation_callback, capture_voice_message
from app.services.capture_confirmation_service import (
    CAPTURE_ACTION_BOSS,
    CAPTURE_ACTION_CANCEL,
    CAPTURE_ACTION_EXPIRED_LATER,
    CAPTURE_ACTION_LATER,
    CAPTURE_ACTION_TASK,
    build_capture_callback_data,
)
from app.services.capture_draft_service import (
    CAPTURE_DRAFT_SOURCE_VOICE,
    CAPTURE_DRAFT_STATUS_CANCELLED,
    CAPTURE_DRAFT_STATUS_CONFIRMED,
    CAPTURE_DRAFT_STATUS_EXPIRED,
    CAPTURE_DRAFT_STATUS_PENDING,
    CaptureDraftService,
)
from app.services.capture_router_service import (
    CAPTURE_KIND_LATER,
    CAPTURE_KIND_TASK,
    CaptureDraft,
)
from app.services.stt_provider import DisabledSTTProvider, FakeSTTProvider, STTResult


CHAT_ID = 555
USER_ID = 123456789


class FakeChat:
    id = CHAT_ID


class FakeUser:
    id = USER_ID


class FakeCallbackMessage:
    def __init__(self):
        self.chat = FakeChat()
        self.answers: list[str] = []
        self.reply_markup_removed = False

    async def answer(self, text: str):
        self.answers.append(text)

    async def edit_reply_markup(self, *, reply_markup=None):
        self.reply_markup_removed = reply_markup is None


class FakeCallback:
    def __init__(self, action: str):
        self.data = build_capture_callback_data(action)
        self.message = FakeCallbackMessage()
        self.from_user = FakeUser()
        self.bot = None
        self.answers: list[tuple[str | None, bool | None]] = []

    async def answer(self, text: str | None = None, *, show_alert: bool | None = None):
        self.answers.append((text, show_alert))


class FakeVoice:
    file_id = "voice-file-id"

    def __init__(self, *, duration: int = 10, file_size: int | None = 1024):
        self.duration = duration
        self.file_size = file_size


class FakeFile:
    file_path = "telegram/voice.ogg"


class FakeBot:
    def __init__(self):
        self.get_file_calls = 0
        self.download_file_calls = 0

    async def get_file(self, file_id: str):
        self.get_file_calls += 1
        assert file_id == "voice-file-id"
        return FakeFile()

    async def download_file(self, file_path: str, *, destination: Path):
        self.download_file_calls += 1
        assert file_path == "telegram/voice.ogg"
        destination.write_bytes(b"fake voice")


class FakeVoiceMessage:
    def __init__(self, *, voice: FakeVoice | None = None):
        self.voice = voice or FakeVoice()
        self.chat = FakeChat()
        self.from_user = FakeUser()
        self.bot = FakeBot()
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))


class RecordingSTTProvider(FakeSTTProvider):
    def __init__(self, transcript: str):
        super().__init__(transcript=transcript)
        self.audio_parent: Path | None = None
        self.audio_exists_during_call = False

    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        self.audio_parent = audio_path.parent
        self.audio_exists_during_call = audio_path.exists()
        return await super().transcribe_audio(audio_path)


def _draft(text: str, kind: str = CAPTURE_KIND_LATER) -> CaptureDraft:
    return CaptureDraft(kind=kind, text=text)


async def _setup_session():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_capture_drafts_")
    db_path = Path(tmp.name) / "capture_drafts.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        echo=False,
        future=True,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return tmp, engine, Session


async def _count_tasks(session) -> int:
    result = await session.execute(select(Task))
    return len(list(result.scalars().all()))


async def test_draft_persists_and_restart_can_read_pending() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            created = await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=_draft("Запомнить мысль"),
            )
            assert created.id is not None
            assert created.status == CAPTURE_DRAFT_STATUS_PENDING

        async with Session() as restarted_session:
            service = CaptureDraftService(restarted_session)
            pending = await service.get_latest_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
            )
            assert pending is not None
            assert pending.raw_text == "Запомнить мысль"
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_confirm_paths_create_items_and_mark_confirmed() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        cases = [
            (CAPTURE_ACTION_TASK, "personal Позвонить маме", "todo"),
            (CAPTURE_ACTION_LATER, "Разобрать идею", "later"),
            (CAPTURE_ACTION_BOSS, "Шеф: отправить отчет", "todo"),
        ]

        for action, text, expected_status in cases:
            async with Session() as session:
                service = CaptureDraftService(session)
                await service.create_pending_draft(
                    chat_id=CHAT_ID,
                    user_id=USER_ID,
                    draft=_draft(text),
                )
                callback = FakeCallback(action)
                await capture_confirmation_callback(callback, session, scheduler=None)

                record = await service._get_latest_by_status(
                    chat_id=CHAT_ID,
                    user_id=USER_ID,
                    status=CAPTURE_DRAFT_STATUS_CONFIRMED,
                )
                assert record is not None

                result = await session.execute(select(Task).order_by(Task.id.desc()))
                task = result.scalars().first()
                assert task is not None
                assert task.status == expected_status
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_cancel_and_unknown_do_not_create_tasks() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            service = CaptureDraftService(session)
            await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=_draft("Не сохранять"),
            )

            callback = FakeCallback(CAPTURE_ACTION_CANCEL)
            await capture_confirmation_callback(callback, session, scheduler=None)

            assert await _count_tasks(session) == 0
            cancelled = await service._get_latest_by_status(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                status=CAPTURE_DRAFT_STATUS_CANCELLED,
            )
            assert cancelled is not None

        async with Session() as session:
            service = CaptureDraftService(session)
            await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=_draft("Оставить pending"),
            )

            callback = FakeCallback("unknown")
            await capture_confirmation_callback(callback, session, scheduler=None)

            assert await _count_tasks(session) == 0
            pending = await service.get_latest_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
            )
            assert pending is not None
            assert pending.raw_text == "Оставить pending"
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_ttl_expiration_waits_for_owner_before_later() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        old_now = datetime.now(timezone.utc) - timedelta(days=3)

        async with Session() as session:
            service = CaptureDraftService(session)
            await service.create_pending_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                draft=_draft("Старая мысль"),
                now=old_now,
            )

            expired_count = await service.expire_old_pending_drafts(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                now=datetime.now(timezone.utc),
            )
            assert expired_count == 1
            assert await _count_tasks(session) == 0

            expired = await service.get_latest_expired_draft(
                chat_id=CHAT_ID,
                user_id=USER_ID,
            )
            assert expired is not None
            assert expired.status == CAPTURE_DRAFT_STATUS_EXPIRED

            callback = FakeCallback(CAPTURE_ACTION_EXPIRED_LATER)
            await capture_confirmation_callback(callback, session, scheduler=None)

            assert await _count_tasks(session) == 1
            confirmed = await service._get_latest_by_status(
                chat_id=CHAT_ID,
                user_id=USER_ID,
                status=CAPTURE_DRAFT_STATUS_CONFIRMED,
            )
            assert confirmed is not None
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_disabled_voice_does_not_download_or_create_draft() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()
            settings = SimpleNamespace(
                stt_max_duration_sec=60,
                stt_max_file_mb=10,
            )
            await capture_voice_message(
                message,
                session,
                settings=settings,
                stt_provider=DisabledSTTProvider(),
            )

            assert message.bot.get_file_calls == 0
            assert message.bot.download_file_calls == 0
            assert len(message.answers) == 1
            assert await _count_tasks(session) == 0

            result = await session.execute(select(CaptureDraftRecord))
            assert list(result.scalars().all()) == []
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_voice_fake_stt_creates_db_draft_without_task() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()
            settings = SimpleNamespace(
                stt_max_duration_sec=60,
                stt_max_file_mb=10,
            )
            stt_provider = RecordingSTTProvider("personal Позвонить маме")

            await capture_voice_message(
                message,
                session,
                settings=settings,
                stt_provider=stt_provider,
            )

            assert message.bot.get_file_calls == 1
            assert message.bot.download_file_calls == 1
            assert stt_provider.audio_exists_during_call is True
            assert stt_provider.audio_parent is not None
            assert not stt_provider.audio_parent.exists()
            assert len(message.answers) == 1
            assert message.answers[0][1] is not None
            assert await _count_tasks(session) == 0

            result = await session.execute(select(CaptureDraftRecord))
            drafts = list(result.scalars().all())
            assert len(drafts) == 1
            draft = drafts[0]
            assert draft.source == CAPTURE_DRAFT_SOURCE_VOICE
            assert draft.raw_text == "personal Позвонить маме"
            assert draft.transcript == "personal Позвонить маме"
            assert draft.suggested_type == CAPTURE_KIND_TASK
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_voice_limits_reject_before_download() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        cases = [
            FakeVoice(duration=61),
            FakeVoice(file_size=(10 * 1024 * 1024) + 1),
        ]
        for voice in cases:
            async with Session() as session:
                message = FakeVoiceMessage(voice=voice)
                settings = SimpleNamespace(
                    stt_max_duration_sec=60,
                    stt_max_file_mb=10,
                )
                await capture_voice_message(
                    message,
                    session,
                    settings=settings,
                    stt_provider=FakeSTTProvider(),
                )

                assert message.bot.get_file_calls == 0
                assert message.bot.download_file_calls == 0
                assert len(message.answers) == 1
                assert await _count_tasks(session) == 0

                result = await session.execute(select(CaptureDraftRecord))
                assert list(result.scalars().all()) == []
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_voice_telegram_download_error_gives_safe_message() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()

            class _FailingBot:
                async def get_file(self, file_id: str):
                    return FakeFile()

                async def download_file(self, file_path: str, *, destination: Path):
                    raise RuntimeError("Telegram download failed")

            message.bot = _FailingBot()
            settings = SimpleNamespace(stt_max_duration_sec=60, stt_max_file_mb=10)
            await capture_voice_message(
                message,
                session,
                settings=settings,
                stt_provider=FakeSTTProvider(),
            )
            assert len(message.answers) == 1, (
                f"expected 1 answer, got {len(message.answers)}"
            )
            assert message.answers[0][0] == "Не удалось обработать голос. Отправь текстом.", (
                f"unexpected message: {message.answers[0][0]!r}"
            )
            result = await session.execute(select(CaptureDraftRecord))
            assert list(result.scalars().all()) == [], "no draft must be created on download error"
            assert await _count_tasks(session) == 0, "no task must be created on download error"
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_voice_unexpected_provider_exception_gives_safe_message() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()

            class _RaisingProvider:
                async def transcribe_audio(self, audio_path: Path) -> STTResult:
                    raise RuntimeError("unexpected provider bug")

            settings = SimpleNamespace(stt_max_duration_sec=60, stt_max_file_mb=10)
            await capture_voice_message(
                message,
                session,
                settings=settings,
                stt_provider=_RaisingProvider(),
            )
            assert len(message.answers) == 1, (
                f"expected 1 answer, got {len(message.answers)}"
            )
            assert message.answers[0][0] == "Не удалось обработать голос. Отправь текстом.", (
                f"unexpected message: {message.answers[0][0]!r}"
            )
            result = await session.execute(select(CaptureDraftRecord))
            assert list(result.scalars().all()) == [], "no draft must be created on provider exception"
            assert await _count_tasks(session) == 0, "no task must be created on provider exception"
    finally:
        await engine.dispose()
        tmp.cleanup()


async def test_voice_cancelled_error_propagates() -> None:
    tmp, engine, Session = await _setup_session()
    try:
        async with Session() as session:
            message = FakeVoiceMessage()

            class _CancellingProvider:
                async def transcribe_audio(self, audio_path: Path) -> STTResult:
                    raise asyncio.CancelledError()

            settings = SimpleNamespace(stt_max_duration_sec=60, stt_max_file_mb=10)
            cancelled_raised = False
            try:
                await capture_voice_message(
                    message,
                    session,
                    settings=settings,
                    stt_provider=_CancellingProvider(),
                )
            except asyncio.CancelledError:
                cancelled_raised = True
            assert cancelled_raised, "CancelledError must propagate, not be swallowed by handler"
            assert len(message.answers) == 0, "no user message must be sent on CancelledError"
    finally:
        await engine.dispose()
        tmp.cleanup()


async def main_async() -> None:
    await test_draft_persists_and_restart_can_read_pending()
    await test_confirm_paths_create_items_and_mark_confirmed()
    await test_cancel_and_unknown_do_not_create_tasks()
    await test_ttl_expiration_waits_for_owner_before_later()
    await test_disabled_voice_does_not_download_or_create_draft()
    await test_voice_fake_stt_creates_db_draft_without_task()
    await test_voice_limits_reject_before_download()
    await test_voice_telegram_download_error_gives_safe_message()
    await test_voice_unexpected_provider_exception_gives_safe_message()
    await test_voice_cancelled_error_propagates()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: capture drafts persist, expire, and require owner confirmation")


if __name__ == "__main__":
    main()
