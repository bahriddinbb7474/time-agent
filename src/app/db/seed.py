from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Rule, UserRoutine
from app.db import crud
from app.core.time import parse_time


TZ = ZoneInfo("Asia/Tashkent")


DEFAULT_RULES = [
    Rule(
        name="Сон",
        start_time=parse_time("23:00"),
        end_time=parse_time("06:30"),
        days_of_week="*",
        policy="never_move",
    ),
    Rule(
        name="Семья",
        start_time=parse_time("19:00"),
        end_time=parse_time("21:00"),
        days_of_week="*",
        policy="never_move",
    ),
    Rule(
        name="Молитва (общий слот)",
        start_time=parse_time("12:30"),
        end_time=parse_time("13:00"),
        days_of_week="*",
        policy="never_move",
    ),
]


async def _seed_user_routines_if_missing(session: AsyncSession) -> None:
    result = await session.execute(select(UserRoutine.mode))
    existing_modes = set(result.scalars().all())

    now = datetime.now(TZ)

    routines_to_add: list[UserRoutine] = []

    if "winter" not in existing_modes:
        routines_to_add.append(
            UserRoutine(
                mode="winter",
                sleep_start=parse_time("23:00"),
                sleep_end=parse_time("05:00"),
                second_sleep_start=None,
                second_sleep_end=None,
                created_at=now,
                updated_at=now,
            )
        )

    if "summer" not in existing_modes:
        routines_to_add.append(
            UserRoutine(
                mode="summer",
                sleep_start=parse_time("23:00"),
                sleep_end=parse_time("02:30"),
                second_sleep_start=parse_time("05:00"),
                second_sleep_end=parse_time("07:00"),
                created_at=now,
                updated_at=now,
            )
        )

    if routines_to_add:
        session.add_all(routines_to_add)
        await session.commit()


async def seed_if_empty(session: AsyncSession) -> None:
    cnt = await crud.count_rules(session)
    if cnt == 0:
        await crud.insert_rules(session, DEFAULT_RULES)

    await _seed_user_routines_if_missing(session)
