"""Stage 20.3-C schedule review callback tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, TimeBlock
from app.handlers.schedule_review import schedule_review_callback
from app.keyboards.schedule_review import schedule_review_callback as callback_data
from app.services.schedule_proposal_builder import ProposalBlockInput, ScheduleProposalBuilder


OWNER_ID = 123456789
DAY = date(2026, 6, 21)
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_review_callbacks_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'callbacks.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


class _Message:
    def __init__(self) -> None:
        self.edits = []

    async def edit_text(self, text, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class _Callback:
    def __init__(self, data: str, user_id: int = OWNER_ID) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _Message()
        self.answers = []

    async def answer(self, text, show_alert=False) -> None:
        self.answers.append((text, show_alert))


def _settings():
    return SimpleNamespace(allowed_telegram_id=OWNER_ID, tz="Asia/Tashkent")


async def _draft(session):
    return await ScheduleProposalBuilder(session).build(
        usage_date=DAY,
        user_id=OWNER_ID,
        timezone="Asia/Tashkent",
        block_inputs=[
            ProposalBlockInput(
                start_at=datetime(2026, 6, 21, 9, tzinfo=TZ),
                end_at=datetime(2026, 6, 21, 10, tzinfo=TZ),
                title="Task",
                category="work",
                block_type="task",
            )
        ],
        collect_project_inputs=False,
    )


async def test_confirm_and_repeated_confirm_are_safe() -> None:
    async with _session_ctx() as session:
        proposal = await _draft(session)
        data = callback_data("confirm", proposal.schedule)
        first = _Callback(data)
        repeated = _Callback(data)
        await schedule_review_callback(first, session, settings=_settings())
        await schedule_review_callback(repeated, session, settings=_settings())
        count = await session.scalar(select(func.count()).select_from(TimeBlock))
        assert proposal.schedule.status == "confirmed"
        assert count == len(proposal.blocks)
        assert "подтверждено" in first.message.edits[-1][0]
        assert repeated.answers[-1][1] is False


async def test_decline_is_idempotent() -> None:
    async with _session_ctx() as session:
        proposal = await _draft(session)
        data = callback_data("decline", proposal.schedule)
        for _ in range(2):
            await schedule_review_callback(_Callback(data), session, settings=_settings())
        assert proposal.schedule.status == "declined"


async def test_rebuild_increments_version_without_duplicate_blocks() -> None:
    async with _session_ctx() as session:
        proposal = await _draft(session)
        callback = _Callback(callback_data("rebuild", proposal.schedule))
        await schedule_review_callback(callback, session, settings=_settings())
        count = await session.scalar(select(func.count()).select_from(TimeBlock))
        assert proposal.schedule.status == "draft"
        assert proposal.schedule.version == 2
        assert count == 0


async def test_rebuild_does_not_replace_confirmed_schedule() -> None:
    async with _session_ctx() as session:
        proposal = await _draft(session)
        await schedule_review_callback(
            _Callback(callback_data("confirm", proposal.schedule)),
            session,
            settings=_settings(),
        )
        callback = _Callback(callback_data("rebuild", proposal.schedule))
        await schedule_review_callback(callback, session, settings=_settings())
        assert proposal.schedule.status == "confirmed"
        assert callback.answers[-1][1] is True


async def test_missing_callback_is_graceful() -> None:
    async with _session_ctx() as session:
        callback = _Callback("schedule_review:confirm:999:1:20260621")
        await schedule_review_callback(callback, session, settings=_settings())
        assert callback.answers[-1][1] is True


async def main_async() -> None:
    await test_confirm_and_repeated_confirm_are_safe()
    await test_decline_is_idempotent()
    await test_rebuild_increments_version_without_duplicate_blocks()
    await test_rebuild_does_not_replace_confirmed_schedule()
    await test_missing_callback_is_graceful()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: schedule review callbacks are idempotent and fail closed")


if __name__ == "__main__":
    main()
