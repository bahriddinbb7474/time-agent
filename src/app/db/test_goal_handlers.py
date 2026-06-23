"""Stage 21-A Telegram goal command tests."""
from __future__ import annotations

import asyncio
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.handlers.goals import (
    goal_add_cmd,
    goal_archive_cmd,
    goal_done_cmd,
    goal_pause_cmd,
    goals_cmd,
)
from app.services.goal_service import GoalService


USER_ID = 123456789


@asynccontextmanager
async def _session_ctx():
    with tempfile.TemporaryDirectory(prefix="time_agent_goal_handlers_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'goal_handlers.db').as_posix()}"
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
    def __init__(self, text: str, user_id: int = USER_ID) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        assert reply_markup is None
        self.answers.append(text)


async def test_goals_lists_non_archived_grouped_by_horizon() -> None:
    async with _session_ctx() as session:
        service = GoalService(session)
        daily = await service.create_goal(
            user_id=USER_ID,
            title="Read Quran",
            horizon="daily",
            time_group="quran",
            preferred_minutes_per_day=30,
        )
        monthly = await service.create_goal(
            user_id=USER_ID,
            title="Sport month",
            horizon="monthly",
            time_group="sport",
            preferred_minutes_per_day=45,
        )
        archived = await service.create_goal(
            user_id=USER_ID,
            title="Hidden",
            horizon="yearly",
            time_group="study",
        )
        await service.archive_goal(user_id=USER_ID, goal_id=archived.id)

        message = _Message("/goals")
        await goals_cmd(message, session)

        text = message.answers[0]
        assert "🎯 Цели" in text
        assert "Сегодня:" in text
        assert "Месяц:" in text
        assert f"{daily.id}. Read Quran" in text
        assert f"{monthly.id}. Sport month" in text
        assert "Hidden" not in text


async def test_goal_add_valid_syntax_creates_goal() -> None:
    async with _session_ctx() as session:
        message = _Message(
            "/goal_add daily quran Читать Коран minutes=30 priority=10"
        )
        await goal_add_cmd(message, session)

        goals = await GoalService(session).list_goals(user_id=USER_ID)
        assert len(goals) == 1
        assert goals[0].horizon == "daily"
        assert goals[0].time_group == "quran"
        assert goals[0].title == "Читать Коран"
        assert goals[0].preferred_minutes_per_day == 30
        assert goals[0].priority == 10
        assert "✅ Цель добавлена" in message.answers[0]


async def test_goal_add_invalid_syntax_returns_help() -> None:
    async with _session_ctx() as session:
        message = _Message("/goal_add daily")
        await goal_add_cmd(message, session)

        assert "Формат:" in message.answers[0]
        assert "/goal_add daily quran" in message.answers[0]
        assert await GoalService(session).list_goals(user_id=USER_ID) == []


async def test_goal_status_commands_update_goal() -> None:
    async with _session_ctx() as session:
        goal = await GoalService(session).create_goal(
            user_id=USER_ID, title="Sport", horizon="monthly", time_group="sport"
        )

        await goal_pause_cmd(_Message(f"/goal_pause {goal.id}"), session)
        assert (await GoalService(session).list_goals(user_id=USER_ID))[0].status == "paused"

        await goal_done_cmd(_Message(f"/goal_done {goal.id}"), session)
        assert (await GoalService(session).list_goals(user_id=USER_ID))[0].status == "done"

        await goal_archive_cmd(_Message(f"/goal_archive {goal.id}"), session)
        assert await GoalService(session).list_goals(user_id=USER_ID) == []
        archived = await GoalService(session).list_goals(
            user_id=USER_ID, include_archived=True
        )
        assert archived[0].status == "archived"


async def main_async() -> None:
    await test_goals_lists_non_archived_grouped_by_horizon()
    await test_goal_add_valid_syntax_creates_goal()
    await test_goal_add_invalid_syntax_returns_help()
    await test_goal_status_commands_update_goal()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: goal Telegram commands implement Stage 21-A MVP")


if __name__ == "__main__":
    main()
