from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TaskExternalLink


class TaskExternalLinkRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_pending(self, task_id: int, provider: str) -> TaskExternalLink:
        """
        Создаёт или обновляет запись sync_pending для задачи.
        """
        existing = await self.get_by_task_and_provider(task_id, provider)

        if existing is not None:
            existing.sync_status = "sync_pending"
            existing.skip_reason = None
            existing.last_error = None
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            return existing

        link = TaskExternalLink(
            task_id=task_id,
            provider=provider,
            sync_status="sync_pending",
            skip_reason=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)

        return link

    async def create_skipped(
        self,
        task_id: int,
        provider: str,
        skip_reason: str,
    ) -> TaskExternalLink:
        """
        Создаёт или обновляет запись skipped_by_policy для задачи.
        """
        existing = await self.get_by_task_and_provider(task_id, provider)

        if existing is not None:
            existing.external_id = None
            existing.external_calendar_id = None
            existing.sync_status = "skipped_by_policy"
            existing.skip_reason = skip_reason
            existing.last_error = None
            existing.last_synced_at = None
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            return existing

        link = TaskExternalLink(
            task_id=task_id,
            provider=provider,
            external_id=None,
            external_calendar_id=None,
            sync_status="skipped_by_policy",
            skip_reason=skip_reason,
            last_error=None,
            last_synced_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)

        return link

    async def create_imported_from_google(
        self,
        *,
        task_id: int,
        provider: str,
        external_id: str,
        calendar_id: str,
    ) -> TaskExternalLink:
        existing = await self.get_by_task_and_provider(task_id, provider)

        if existing is not None:
            existing.external_id = external_id
            existing.external_calendar_id = calendar_id
            existing.sync_status = "imported_from_google"
            existing.skip_reason = None
            existing.last_error = None
            existing.last_synced_at = datetime.now(timezone.utc)
            existing.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            return existing

        link = TaskExternalLink(
            task_id=task_id,
            provider=provider,
            external_id=external_id,
            external_calendar_id=calendar_id,
            sync_status="imported_from_google",
            skip_reason=None,
            last_error=None,
            last_synced_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.session.add(link)
        await self.session.commit()
        await self.session.refresh(link)

        return link

    async def get_by_task_and_provider(
        self,
        task_id: int,
        provider: str,
    ) -> TaskExternalLink | None:
        stmt = select(TaskExternalLink).where(
            TaskExternalLink.task_id == task_id,
            TaskExternalLink.provider == provider,
        )

        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_by_external_id(
        self,
        *,
        provider: str,
        external_id: str,
    ) -> TaskExternalLink | None:
        stmt = select(TaskExternalLink).where(
            TaskExternalLink.provider == provider,
            TaskExternalLink.external_id == external_id,
        )

        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def exists_synced(self, task_id: int, provider: str) -> bool:
        stmt = select(TaskExternalLink).where(
            TaskExternalLink.task_id == task_id,
            TaskExternalLink.provider == provider,
            TaskExternalLink.sync_status == "synced",
        )

        res = await self.session.execute(stmt)
        return res.scalars().first() is not None

    async def mark_synced(
        self,
        task_id: int,
        provider: str,
        external_id: str,
        calendar_id: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)

        if link is None:
            return

        link.external_id = external_id
        link.external_calendar_id = calendar_id
        link.sync_status = "synced"
        link.skip_reason = None
        link.last_error = None
        link.last_synced_at = datetime.now(timezone.utc)
        link.updated_at = datetime.now(timezone.utc)

        await self.session.commit()

    async def mark_failed(
        self,
        task_id: int,
        provider: str,
        error_text: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)

        if link is None:
            return

        link.sync_status = "sync_failed"
        link.skip_reason = None
        link.last_error = error_text[:500]
        link.updated_at = datetime.now(timezone.utc)

        await self.session.commit()

    async def mark_update_pending(
        self,
        task_id: int,
        provider: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)
        if link is None:
            await self.create_pending(task_id, provider)
            link = await self.get_by_task_and_provider(task_id, provider)

        if link is None:
            return

        link.sync_status = "update_pending"
        link.skip_reason = None
        link.last_error = None
        link.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_update_failed(
        self,
        task_id: int,
        provider: str,
        error_text: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)
        if link is None:
            return

        link.sync_status = "update_failed"
        link.skip_reason = None
        link.last_error = error_text[:500]
        link.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_delete_pending(
        self,
        task_id: int,
        provider: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)
        if link is None:
            return

        link.sync_status = "delete_pending"
        link.last_error = None
        link.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_delete_failed(
        self,
        task_id: int,
        provider: str,
        error_text: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)
        if link is None:
            return

        link.sync_status = "delete_failed"
        link.last_error = error_text[:500]
        link.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def mark_deleted_external(
        self,
        task_id: int,
        provider: str,
    ) -> None:
        link = await self.get_by_task_and_provider(task_id, provider)
        if link is None:
            return

        link.sync_status = "deleted_external"
        link.last_error = None
        link.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
