"""Stage 21-A GoalService tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.services.goal_service import (
    GoalNotFoundError,
    GoalService,
    GoalValidationError,
)


USER_ID = 123456789
OTHER_USER_ID = 987654321


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_goals_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'goals.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


async def test_create_valid_goal() -> None:
    async with _session_ctx() as session:
        goal = await GoalService(session).create_goal(
            user_id=USER_ID,
            title="Read Quran",
            horizon="daily",
            time_group="quran",
            preferred_minutes_per_day=30,
            priority=10,
        )
        assert goal.id is not None
        assert goal.user_id == USER_ID
        assert goal.status == "active"
        assert goal.time_group == "quran"
        assert goal.preferred_minutes_per_day == 30


async def test_invalid_horizon_rejected() -> None:
    async with _session_ctx() as session:
        try:
            await GoalService(session).create_goal(
                user_id=USER_ID,
                title="Bad",
                horizon="weekly",
                time_group="quran",
            )
            raise AssertionError("expected GoalValidationError")
        except GoalValidationError:
            pass


async def test_invalid_time_group_rejected() -> None:
    async with _session_ctx() as session:
        try:
            await GoalService(session).create_goal(
                user_id=USER_ID,
                title="Bad",
                horizon="daily",
                time_group="unknown_group",
            )
            raise AssertionError("expected GoalValidationError")
        except GoalValidationError:
            pass


async def test_no_data_and_waste_rejected_as_goal_groups() -> None:
    async with _session_ctx() as session:
        for group in ("undefined", "no_data", "waste"):
            try:
                await GoalService(session).create_goal(
                    user_id=USER_ID,
                    title="Bad",
                    horizon="daily",
                    time_group=group,
                )
                raise AssertionError(f"expected GoalValidationError for {group}")
            except GoalValidationError:
                pass


async def test_list_excludes_archived_by_default() -> None:
    async with _session_ctx() as session:
        service = GoalService(session)
        active = await service.create_goal(
            user_id=USER_ID, title="Active", horizon="daily", time_group="quran"
        )
        paused = await service.create_goal(
            user_id=USER_ID, title="Paused", horizon="monthly", time_group="sport"
        )
        done = await service.create_goal(
            user_id=USER_ID, title="Done", horizon="yearly", time_group="ai_projects"
        )
        archived = await service.create_goal(
            user_id=USER_ID, title="Archived", horizon="daily", time_group="study"
        )
        await service.pause_goal(user_id=USER_ID, goal_id=paused.id)
        await service.mark_done(user_id=USER_ID, goal_id=done.id)
        await service.archive_goal(user_id=USER_ID, goal_id=archived.id)

        visible = await service.list_goals(user_id=USER_ID)
        all_goals = await service.list_goals(user_id=USER_ID, include_archived=True)
        assert {goal.id for goal in visible} == {active.id, paused.id, done.id}
        assert {goal.id for goal in all_goals} == {
            active.id,
            paused.id,
            done.id,
            archived.id,
        }


async def test_archive_pause_done_change_status() -> None:
    async with _session_ctx() as session:
        service = GoalService(session)
        goal = await service.create_goal(
            user_id=USER_ID, title="Sport", horizon="monthly", time_group="sport"
        )
        assert (await service.pause_goal(user_id=USER_ID, goal_id=goal.id)).status == "paused"
        assert (await service.mark_done(user_id=USER_ID, goal_id=goal.id)).status == "done"
        assert (
            await service.archive_goal(user_id=USER_ID, goal_id=goal.id)
        ).status == "archived"


async def test_user_isolation_on_mutation() -> None:
    async with _session_ctx() as session:
        service = GoalService(session)
        goal = await service.create_goal(
            user_id=USER_ID, title="Quran", horizon="daily", time_group="quran"
        )
        try:
            await service.archive_goal(user_id=OTHER_USER_ID, goal_id=goal.id)
            raise AssertionError("expected GoalNotFoundError")
        except GoalNotFoundError:
            pass
        visible = await service.list_goals(user_id=USER_ID)
        assert visible[0].status == "active"


async def main_async() -> None:
    await test_create_valid_goal()
    await test_invalid_horizon_rejected()
    await test_invalid_time_group_rejected()
    await test_no_data_and_waste_rejected_as_goal_groups()
    await test_list_excludes_archived_by_default()
    await test_archive_pause_done_change_status()
    await test_user_isolation_on_mutation()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: GoalService stores and validates Stage 21-A goals")


if __name__ == "__main__":
    main()
