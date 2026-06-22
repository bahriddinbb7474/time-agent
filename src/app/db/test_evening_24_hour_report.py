"""Stage 20-FINAL Block 4 compact evening mirror formatter tests."""
from __future__ import annotations

import asyncio
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.scheduler.jobs import evening_summary
from app.services.daily_control_accounting_service import DailyControlAccounting
from app.services.evening_planning_service import build_evening_24_hour_lines


def _accounting(
    *,
    category_minutes=None,
    unknown_minutes=0.0,
    no_data_minutes=0.0,
    waste_minutes=0.0,
    protected_minutes=0.0,
) -> DailyControlAccounting:
    categories = category_minutes or {}
    actual = sum(categories.values())
    return DailyControlAccounting(
        usage_date=date(2026, 6, 21),
        total_minutes=1440.0,
        planned_minutes=0.0,
        actual_minutes=actual,
        plan_variance_minutes=actual,
        useful_outside_plan_minutes=actual,
        unaccounted_minutes=0.0,
        no_data_minutes=no_data_minutes,
        unknown_minutes=unknown_minutes,
        protected_minutes=protected_minutes,
        owner_marked_waste_minutes=waste_minutes,
        category_minutes=categories,
    )


def test_groups_unknown_no_data_waste_and_plan_are_compact() -> None:
    lines = build_evening_24_hour_lines(
        _accounting(
            category_minutes={
                "sleep": 440.0,
                "work": 420.0,
                "ai_projects": 100.0,
                "waste": 30.0,
            },
            unknown_minutes=30.0,
            no_data_minutes=120.0,
            waste_minutes=30.0,
        ),
        done_count=5,
        unfinished_count=1,
    )
    text = "\n".join(lines)
    assert "Сон: 7ч 20м" in text
    assert "Работа: 7ч" in text
    assert "ИИ-кодинг / проекты: 1ч 40м" in text
    assert "Не помню: 30м" in text
    assert "Не определено: 2ч" in text
    assert "Впустую: 30м" in text
    assert "✅ Сделано: 5" in text
    assert "❌ Не сделано по плану: 1" in text
    assert "⏱ Подтверждено фактом: 16ч 30м" in text
    assert "Коран:" not in text
    assert "Спорт:" not in text


def test_waste_is_hidden_without_owner_confirmed_waste_minutes() -> None:
    text = "\n".join(
        build_evening_24_hour_lines(
            _accounting(
                category_minutes={"waste": 30.0},
                no_data_minutes=30.0,
                waste_minutes=0.0,
            )
        )
    )
    assert "Впустую:" not in text
    assert "Не определено: 1ч" in text


def test_advice_is_deterministic() -> None:
    high_no_data = "\n".join(
        build_evening_24_hour_lines(_accounting(no_data_minutes=180.0))
    )
    assert "чаще отвечай на check-in" in high_no_data

    no_sport = "\n".join(
        build_evening_24_hour_lines(
            _accounting(
                category_minutes={"work": 600.0, "family_time": 60.0},
                no_data_minutes=30.0,
            )
        )
    )
    assert "короткую ходьбу" in no_sport

    good_coverage = "\n".join(
        build_evening_24_hour_lines(
            _accounting(
                category_minutes={
                    "work": 600.0,
                    "sport": 30.0,
                    "family_time": 60.0,
                },
                no_data_minutes=30.0,
            )
        )
    )
    assert "выбери 2 главных блока" in good_coverage


class _Bot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


async def test_evening_job_appends_mirror_to_existing_message() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_evening_mirror_") as tmp:
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{(Path(tmp) / 'evening.db').as_posix()}"
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        accounting = _accounting(
            category_minutes={"work": 420.0, "sport": 30.0},
            unknown_minutes=30.0,
            no_data_minutes=60.0,
        )
        bot = _Bot()
        with (
            patch("app.scheduler.jobs.get_sessionmaker", return_value=Session),
            patch(
                "app.scheduler.jobs.load_config",
                return_value=SimpleNamespace(allowed_telegram_id=123),
            ),
            patch(
                "app.scheduler.jobs.TaskService.list_today",
                AsyncMock(return_value=([], [])),
            ),
            patch(
                "app.scheduler.jobs.TaskService.list_done_for_date",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs.TaskService.list_later",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs.TaskService.list_tomorrow",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs.QuranService.get_daily_summary",
                AsyncMock(return_value=SimpleNamespace(goal_reached=True)),
            ),
            patch(
                "app.scheduler.jobs.QuranService.build_deficit_message",
                MagicMock(return_value="• Quran: ok"),
            ),
            patch(
                "app.scheduler.jobs._build_prayer_status_section",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs._build_health_status_section",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs._build_targets_evening_section",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.scheduler.jobs.DailyControlAccountingService.summarize",
                AsyncMock(return_value=accounting),
            ),
            patch(
                "app.scheduler.jobs._send_hydration_runtime_ping",
                AsyncMock(),
            ),
        ):
            await evening_summary(bot)

        assert len(bot.sent) == 1
        message = bot.sent[0][1]
        assert "Итог 24 часов" in message
        assert "Работа: 7ч" in message
        assert "Не помню: 30м" in message
        assert "Не определено: 1ч" in message
        assert "Что главное завтра?" in message
        await engine.dispose()


if __name__ == "__main__":
    test_groups_unknown_no_data_waste_and_plan_are_compact()
    test_waste_is_hidden_without_owner_confirmed_waste_minutes()
    test_advice_is_deterministic()
    asyncio.run(test_evening_job_appends_mirror_to_existing_message())
    print("PASS: evening 24-hour report is compact, honest, and deterministic")
