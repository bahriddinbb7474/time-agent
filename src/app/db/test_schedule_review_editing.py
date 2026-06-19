"""Stage 20.3-D safe edit foundation tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.handlers.schedule_review import schedule_review_callback
from app.keyboards.schedule_review import schedule_review_callback as callback_data
from app.services.daily_control_service import TimeBlockService
from app.services.schedule_proposal_builder import ProposalBlockInput, ScheduleProposalBuilder


OWNER_ID = 123456789
DAY = date(2026, 6, 21)
TZ = timezone(timedelta(hours=5))


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_review_editing_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'editing.db').as_posix()}"
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
    def __init__(self, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=OWNER_ID)
        self.message = _Message()
        self.answers = []

    async def answer(self, text, show_alert=False) -> None:
        self.answers.append((text, show_alert))


async def test_edit_is_explicit_stub_and_never_mutates_protected_blocks() -> None:
    async with _session_ctx() as session:
        proposal = await ScheduleProposalBuilder(session).build(
            usage_date=DAY,
            user_id=OWNER_ID,
            timezone="Asia/Tashkent",
            block_inputs=[
                ProposalBlockInput(
                    start_at=datetime(2026, 6, 21, 0, tzinfo=TZ),
                    end_at=datetime(2026, 6, 21, 6, tzinfo=TZ),
                    title="Sleep",
                    category="sleep",
                    block_type="sleep",
                    flexibility="protected",
                ),
                ProposalBlockInput(
                    start_at=datetime(2026, 6, 21, 6, 15, tzinfo=TZ),
                    end_at=datetime(2026, 6, 21, 6, 35, tzinfo=TZ),
                    title="Prayer",
                    category="prayer",
                    block_type="prayer",
                    flexibility="protected",
                ),
            ],
            collect_project_inputs=False,
        )
        before = [
            (block.id, block.start_at, block.end_at, block.block_type)
            for block in proposal.blocks
        ]
        callback = _Callback(callback_data("edit", proposal.schedule))
        await schedule_review_callback(
            callback,
            session,
            settings=SimpleNamespace(
                allowed_telegram_id=OWNER_ID, tz="Asia/Tashkent"
            ),
        )
        after_blocks = await TimeBlockService(session).list(
            schedule_id=proposal.schedule.id, user_id=OWNER_ID
        )
        after = [
            (block.id, block.start_at, block.end_at, block.block_type)
            for block in after_blocks
        ]

        assert after == before
        text, keyboard = callback.message.edits[-1]
        assert "Точечные правки будут подключены следующим шагом" in text
        assert "сна и намаза не изменяются" in text
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        assert [button.text for button in buttons] == ["🔄 Rebuild current inputs"]
        assert callback.answers[-1][1] is False


def main() -> None:
    asyncio.run(test_edit_is_explicit_stub_and_never_mutates_protected_blocks())
    print("PASS: schedule edit foundation preserves protected blocks")


if __name__ == "__main__":
    main()
