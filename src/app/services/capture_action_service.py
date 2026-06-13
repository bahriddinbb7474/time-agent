from __future__ import annotations

import re

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.add import parse_add_payload
from app.services.task_create_service import CreateTaskResultDTO, TaskCreateService
from app.services.task_service import TaskDTO, TaskService


class CaptureActionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        scheduler: AsyncIOScheduler | None = None,
        bot=None,
    ):
        self.session = session
        self.scheduler = scheduler
        self.bot = bot

    async def create_task_from_text(
        self,
        text: str,
        *,
        user_id: int | None = None,
    ) -> CreateTaskResultDTO:
        category, title, planned_at, duration_min = parse_add_payload(text)
        task_service = TaskCreateService(
            session=self.session,
            scheduler=self.scheduler,
            bot=self.bot,
        )
        return await task_service.create_task(
            title=title,
            planned_at=planned_at,
            duration_min=duration_min,
            category=category,
            user_id=user_id,
        )

    async def create_later_from_text(self, text: str) -> TaskDTO:
        return await TaskService(self.session).create_later(text.strip())

    async def create_boss_from_text(
        self,
        text: str,
        *,
        user_id: int | None = None,
    ) -> TaskDTO:
        payload = self._normalize_boss_payload(text)
        return await TaskService(self.session).create_task(
            title=f"Шеф: {payload}",
            planned_at=None,
            duration_min=30,
            category="work",
            priority_code="BOSS_CRITICAL",
            user_id=user_id,
        )

    @staticmethod
    def _normalize_boss_payload(text: str) -> str:
        raw = text.strip()
        raw = re.sub(r"^(boss|шеф)\s*:?\s*", "", raw, flags=re.IGNORECASE).strip()
        return raw or "Задача"
