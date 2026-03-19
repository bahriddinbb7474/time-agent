from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db import crud


@dataclass
class RuleDTO:
    name: str
    start_time: str
    end_time: str
    days_of_week: str
    policy: str


class RulesService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_rules(self) -> list[RuleDTO]:
        rules = await crud.list_rules(self.session)

        return [
            RuleDTO(
                name=r.name,
                start_time=r.start_time.strftime("%H:%M"),
                end_time=r.end_time.strftime("%H:%M"),
                days_of_week=r.days_of_week,
                policy=r.policy,
            )
            for r in rules
        ]

    async def check_conflicts(
        self,
        planned_at: datetime,
        duration_min: int,
    ) -> list[RuleDTO]:

        start = planned_at.astimezone(APP_TZ)
        end = start + timedelta(minutes=duration_min)

        rules = await self.list_rules()
        conflicts: list[RuleDTO] = []

        def overlaps(a_start, a_end, b_start, b_end):
            return a_start < b_end and b_start < a_end

        for r in rules:
            if r.policy != "never_move":
                continue

            start_time_obj = datetime.strptime(r.start_time, "%H:%M").time()
            end_time_obj = datetime.strptime(r.end_time, "%H:%M").time()

            day = start.date()
            prev_day = day - timedelta(days=1)
            next_day = day + timedelta(days=1)

            # ===== ОБЫЧНЫЙ СЛОТ =====
            if end_time_obj > start_time_obj:
                rs = datetime.combine(day, start_time_obj, tzinfo=APP_TZ)
                re = datetime.combine(day, end_time_obj, tzinfo=APP_TZ)

                if overlaps(start, end, rs, re):
                    conflicts.append(r)

            # ===== НОЧНОЙ СЛОТ =====
            else:
                # предыдущая ночь
                rs_prev = datetime.combine(prev_day, start_time_obj, tzinfo=APP_TZ)
                re_prev = datetime.combine(day, end_time_obj, tzinfo=APP_TZ)

                # текущая ночь
                rs_curr = datetime.combine(day, start_time_obj, tzinfo=APP_TZ)
                re_curr = datetime.combine(next_day, end_time_obj, tzinfo=APP_TZ)

                if overlaps(start, end, rs_prev, re_prev) or overlaps(
                    start, end, rs_curr, re_curr
                ):
                    conflicts.append(r)

        return conflicts
