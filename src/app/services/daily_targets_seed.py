from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyTargetDefinition
from app.services.daily_targets_service import DailyTargetsService


# Default targets from TZ section 18.7 (docs/TZ_TIME_AGENT_FINAL_v8_1.md lines ~369-376).
# Units are given in the input form; DailyTargetsService.normalize converts them to
# canonical storage units at write time (liters→ml, hours→minutes).
DEFAULT_TARGETS: list[dict] = [
    {
        "title": "Вода",
        "unit": "liters",
        "target_value": 3.0,
        "category": "health",
        "target_mode": "minimum",
        "priority": 100,
        "weekdays_mask": 127,
    },
    {
        "title": "Сон",
        "unit": "hours",
        "target_value": 6.0,
        "category": "health",
        "target_mode": "minimum",
        "priority": 90,
        "weekdays_mask": 127,
    },
    {
        "title": "Каза-намаз",
        "unit": "count",
        "target_value": 5.0,
        "category": "prayer",
        "target_mode": "minimum",
        "priority": 80,
        "weekdays_mask": 127,
    },
    {
        "title": "Коран",
        "unit": "pages",
        "target_value": 20.0,
        "category": "quran",
        "target_mode": "minimum",
        "priority": 70,
        "weekdays_mask": 127,
    },
    {
        "title": "Английский",
        "unit": "minutes",
        "target_value": 30.0,
        "category": "study",
        "target_mode": "minimum",
        "priority": 60,
        "weekdays_mask": 127,
    },
    {
        "title": "Коран с детьми",
        "unit": "minutes",
        "target_value": 30.0,
        "category": "family",
        "target_mode": "minimum",
        "priority": 50,
        "weekdays_mask": 127,
    },
]


async def seed_default_targets(session: AsyncSession) -> list[str]:
    """
    Create default daily targets that do not yet exist (matched by title).

    Idempotent: repeated calls never create duplicates and never overwrite
    existing rows, even if the user edited their values.

    Returns the list of titles that were newly created.
    """
    result = await session.execute(select(DailyTargetDefinition.title))
    existing_titles: set[str] = {row[0] for row in result}

    service = DailyTargetsService(session)
    created: list[str] = []
    for spec in DEFAULT_TARGETS:
        if spec["title"] not in existing_titles:
            await service.create_target_definition(**spec)
            created.append(spec["title"])
    return created
