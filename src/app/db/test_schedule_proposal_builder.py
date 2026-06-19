"""Stage 20.2 schedule proposal builder tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.daily_control_service import DailyControlValidationError
from app.services.schedule_proposal_builder import (
    PROPOSAL_TYPE,
    ProposalBlockInput,
    ScheduleProposalBuilder,
)


USER_ID = 123456789
TZ_NAME = "Asia/Tashkent"
TZ = ZoneInfo(TZ_NAME)
USAGE_DATE = date(2026, 6, 20)


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_schedule_proposal_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'proposal.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


def _block(hour: int, title: str, block_type: str) -> ProposalBlockInput:
    return ProposalBlockInput(
        start_at=datetime(2026, 6, 20, hour, tzinfo=TZ),
        end_at=datetime(2026, 6, 20, hour + 1, tzinfo=TZ),
        title=title,
        category=block_type,
        block_type=block_type,
    )


async def test_builds_deterministic_idempotent_draft() -> None:
    async with _session_ctx() as session:
        builder = ScheduleProposalBuilder(session)
        inputs = [_block(10, "Task", "task"), _block(8, "Sleep", "sleep")]
        first = await builder.build(
            usage_date=USAGE_DATE,
            user_id=USER_ID,
            timezone=TZ_NAME,
            block_inputs=inputs,
        )
        second = await builder.build(
            usage_date=USAGE_DATE,
            user_id=USER_ID,
            timezone=TZ_NAME,
            block_inputs=list(reversed(inputs)),
        )

        assert first.proposal_type == PROPOSAL_TYPE
        assert first.schedule.status == "draft"
        assert first.version == 1
        assert [block.title for block in first.blocks] == ["Sleep", "Task"]
        assert second.schedule.id == first.schedule.id
        assert [block.id for block in second.blocks] == [block.id for block in first.blocks]


async def test_empty_proposal_and_validation() -> None:
    async with _session_ctx() as session:
        builder = ScheduleProposalBuilder(session)
        empty = await builder.build(
            usage_date=USAGE_DATE, user_id=USER_ID, timezone=TZ_NAME
        )
        assert empty.blocks == ()

        try:
            await builder.build(
                usage_date=date(2026, 6, 21),
                user_id=USER_ID,
                timezone=TZ_NAME,
                block_inputs=[_block(12, "Unknown", "unknown")],
            )
            raise AssertionError("unsupported block type must fail")
        except DailyControlValidationError:
            pass


async def main_async() -> None:
    await test_builds_deterministic_idempotent_draft()
    await test_empty_proposal_and_validation()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: schedule proposal builder creates deterministic idempotent drafts")


if __name__ == "__main__":
    main()
