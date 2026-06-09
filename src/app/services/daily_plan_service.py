from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import crud


@dataclass(slots=True)
class DailyPlanDTO:
    id: int
    plan_date: date
    text: str
    source: str


class DailyPlanService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_plan(
        self,
        *,
        plan_date: date,
        text: str,
        source: str = "telegram_manual",
    ) -> DailyPlanDTO:
        plan = await crud.save_daily_plan(
            self.session,
            plan_date=plan_date,
            text=text,
            source=source,
        )
        return self._to_dto(plan)

    async def get_plan(self, plan_date: date) -> DailyPlanDTO | None:
        plan = await crud.get_daily_plan(self.session, plan_date)
        if plan is None:
            return None
        return self._to_dto(plan)

    @staticmethod
    def _to_dto(plan) -> DailyPlanDTO:
        return DailyPlanDTO(
            id=plan.id,
            plan_date=plan.plan_date,
            text=plan.text,
            source=plan.source,
        )
