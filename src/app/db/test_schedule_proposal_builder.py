"""Stage 20.2 schedule proposal builder tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, PrayerTime, Task, UserRoutine
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
        assert [block.title for block in first.blocks] == ["Sleep", "Task", "Buffer"]
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


async def test_protected_priority_and_overload() -> None:
    async with _session_ctx() as session:
        builder = ScheduleProposalBuilder(session)
        sleep = ProposalBlockInput(
            start_at=datetime(2026, 6, 20, 0, tzinfo=TZ),
            end_at=datetime(2026, 6, 20, 7, tzinfo=TZ),
            title="Sleep",
            category="sleep",
            block_type="sleep",
        )
        prayer = ProposalBlockInput(
            start_at=datetime(2026, 6, 20, 7, 15, tzinfo=TZ),
            end_at=datetime(2026, 6, 20, 7, 35, tzinfo=TZ),
            title="Prayer",
            category="prayer",
            block_type="prayer",
        )
        conflicting_task = ProposalBlockInput(
            start_at=datetime(2026, 6, 20, 6, 30, tzinfo=TZ),
            end_at=datetime(2026, 6, 20, 7, 30, tzinfo=TZ),
            title="Overload",
            category="work",
            block_type="task",
        )
        proposal = await builder.build(
            usage_date=USAGE_DATE,
            user_id=USER_ID,
            timezone=TZ_NAME,
            block_inputs=[conflicting_task, prayer, sleep],
        )

        assert [block.block_type for block in proposal.blocks] == [
            "sleep",
            "prayer",
            "buffer",
        ]
        assert len(proposal.unscheduled_items) == 1
        assert proposal.unscheduled_items[0].item.title == "Overload"
        assert "higher-priority" in proposal.unscheduled_items[0].reason
        buffer = proposal.blocks[-1]
        assert buffer.end_at > buffer.start_at


async def test_overlapping_sleep_and_prayer_are_normalized() -> None:
    async with _session_ctx() as session:
        builder = ScheduleProposalBuilder(session)
        inputs = [
            ProposalBlockInput(
                start_at=datetime(2026, 6, 20, 0, tzinfo=TZ),
                end_at=datetime(2026, 6, 20, 7, tzinfo=TZ),
                title="Sleep",
                category="sleep",
                block_type="sleep",
            ),
            ProposalBlockInput(
                start_at=datetime(2026, 6, 20, 5, 30, tzinfo=TZ),
                end_at=datetime(2026, 6, 20, 6, 30, tzinfo=TZ),
                title="Fajr",
                category="prayer",
                block_type="prayer",
            ),
            ProposalBlockInput(
                start_at=datetime(2026, 6, 20, 5, 45, tzinfo=TZ),
                end_at=datetime(2026, 6, 20, 6, 15, tzinfo=TZ),
                title="Task inside protected time",
                category="work",
                block_type="task",
            ),
        ]
        first = await builder.build(
            usage_date=USAGE_DATE,
            user_id=USER_ID,
            timezone=TZ_NAME,
            block_inputs=inputs,
            collect_project_inputs=False,
        )
        second = await builder.build(
            usage_date=USAGE_DATE,
            user_id=USER_ID,
            timezone=TZ_NAME,
            block_inputs=list(reversed(inputs)),
            collect_project_inputs=False,
        )

        protected = [
            block for block in first.blocks if block.block_type in {"sleep", "prayer"}
        ]
        assert [block.block_type for block in protected] == [
            "sleep",
            "prayer",
            "sleep",
        ]
        for left, right in zip(protected, protected[1:]):
            assert left.end_at <= right.start_at
        assert all(block.title != "Task inside protected time" for block in first.blocks)
        reasons = [item.reason for item in first.unscheduled_items]
        assert any("split around protected prayer" in reason for reason in reasons)
        assert any("higher-priority prayer" in reason for reason in reasons)
        assert [block.id for block in second.blocks] == [
            block.id for block in first.blocks
        ]


async def test_collects_cached_project_inputs_without_source_mutation() -> None:
    async with _session_ctx() as session:
        created_at = datetime(2026, 6, 19, 12, tzinfo=TZ)
        task = Task(
            title="Timed task",
            planned_at=datetime(2026, 6, 20, 10, tzinfo=TZ),
            duration_min=45,
            status="todo",
            category="work",
            context_status="normal",
            created_at=created_at,
        )
        session.add_all(
            [
                task,
                PrayerTime(
                    date=USAGE_DATE,
                    fajr=datetime(2026, 6, 20, 4, 30).time(),
                    dhuhr=datetime(2026, 6, 20, 12, 30).time(),
                    asr=datetime(2026, 6, 20, 17, 0).time(),
                    maghrib=datetime(2026, 6, 20, 19, 45).time(),
                    isha=datetime(2026, 6, 20, 21, 15).time(),
                    created_at=created_at,
                ),
                UserRoutine(
                    mode="summer",
                    sleep_start=datetime(2026, 6, 20, 23, 0).time(),
                    sleep_end=datetime(2026, 6, 20, 4, 0).time(),
                    second_sleep_start=None,
                    second_sleep_end=None,
                    created_at=created_at,
                    updated_at=created_at,
                ),
            ]
        )
        await session.commit()

        proposal = await ScheduleProposalBuilder(session).build(
            usage_date=USAGE_DATE, user_id=USER_ID, timezone=TZ_NAME
        )

        block_types = [block.block_type for block in proposal.blocks]
        assert block_types.count("sleep") == 2
        assert block_types.count("prayer") == 5
        assert "fixed_task" in block_types
        assert proposal.unscheduled_items == ()
        assert task.status == "todo"
        assert task.planned_at is not None


async def test_missing_inputs_return_safe_partial_proposal() -> None:
    async with _session_ctx() as session:
        proposal = await ScheduleProposalBuilder(session).build(
            usage_date=USAGE_DATE, user_id=USER_ID, timezone=TZ_NAME
        )
        assert proposal.blocks == ()
        assert proposal.unscheduled_items == ()


async def main_async() -> None:
    await test_builds_deterministic_idempotent_draft()
    await test_empty_proposal_and_validation()
    await test_protected_priority_and_overload()
    await test_overlapping_sleep_and_prayer_are_normalized()
    await test_collects_cached_project_inputs_without_source_mutation()
    await test_missing_inputs_return_safe_partial_proposal()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: schedule proposal builder creates deterministic idempotent drafts")


if __name__ == "__main__":
    main()
