"""Stage 20.3-A durable schedule confirmation tests. Temp SQLite only."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.daily_control_service import (
    DailyControlNotFoundError,
    DailyScheduleService,
)
from app.services.schedule_confirmation_service import (
    ScheduleConfirmationConflictError,
    ScheduleConfirmationService,
)


USER_ID = 123456789
USAGE_DATE = date(2026, 6, 21)


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_schedule_confirmation_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'confirmation.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_confirm_is_owner_scoped_and_idempotent() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=USAGE_DATE
        )
        service = ScheduleConfirmationService(session)
        first = await service.confirm(
            schedule_id=schedule.id,
            user_id=USER_ID,
            usage_date=USAGE_DATE,
            version=1,
        )
        repeated = await service.confirm(
            schedule_id=schedule.id,
            user_id=USER_ID,
            usage_date=USAGE_DATE,
            version=1,
        )
        assert first.status == "confirmed"
        assert repeated.id == first.id
        assert repeated.version == 1
        assert repeated.confirmed_at is not None
        try:
            await service.confirm(
                schedule_id=schedule.id,
                user_id=USER_ID + 1,
                usage_date=USAGE_DATE,
                version=1,
            )
            raise AssertionError("other owner must not confirm proposal")
        except DailyControlNotFoundError:
            pass


async def test_decline_and_other_terminal_states_are_idempotent() -> None:
    for target in ("declined", "expired", "cancelled"):
        async with _session_ctx() as session:
            schedule = await DailyScheduleService(session).create(
                user_id=USER_ID, usage_date=USAGE_DATE
            )
            service = ScheduleConfirmationService(session)
            method = getattr(service, "decline" if target == "declined" else target[:-1] if target == "expired" else "cancel")
            first = await method(
                schedule_id=schedule.id,
                user_id=USER_ID,
                usage_date=USAGE_DATE,
                version=1,
            )
            repeated = await method(
                schedule_id=schedule.id,
                user_id=USER_ID,
                usage_date=USAGE_DATE,
                version=1,
            )
            assert first.status == target
            assert repeated.status == target


async def test_stale_or_wrong_date_transition_fails_closed() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=USAGE_DATE
        )
        service = ScheduleConfirmationService(session)
        for usage_date, version in ((date(2026, 6, 22), 1), (USAGE_DATE, 2)):
            try:
                await service.decline(
                    schedule_id=schedule.id,
                    user_id=USER_ID,
                    usage_date=usage_date,
                    version=version,
                )
                raise AssertionError("stale proposal transition must fail")
            except ScheduleConfirmationConflictError:
                pass


async def test_terminal_state_cannot_change_to_another_terminal_state() -> None:
    async with _session_ctx() as session:
        schedule = await DailyScheduleService(session).create(
            user_id=USER_ID, usage_date=USAGE_DATE
        )
        service = ScheduleConfirmationService(session)
        await service.confirm(
            schedule_id=schedule.id,
            user_id=USER_ID,
            usage_date=USAGE_DATE,
            version=1,
        )
        try:
            await service.decline(
                schedule_id=schedule.id,
                user_id=USER_ID,
                usage_date=USAGE_DATE,
                version=1,
            )
            raise AssertionError("confirmed proposal must not become declined")
        except ScheduleConfirmationConflictError:
            pass


async def main_async() -> None:
    await test_confirm_is_owner_scoped_and_idempotent()
    await test_decline_and_other_terminal_states_are_idempotent()
    await test_stale_or_wrong_date_transition_fails_closed()
    await test_terminal_state_cannot_change_to_another_terminal_state()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: schedule proposal confirmation transitions are durable and idempotent")


if __name__ == "__main__":
    main()
