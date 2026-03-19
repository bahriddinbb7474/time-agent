from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db.oauth_state_repo import OAuthStateRepo
from app.integrations.google.auth import build_flow, load_credentials, refresh_if_needed
from app.integrations.google.calendar_client import (
    create_event as google_create_event,
    delete_event as google_delete_event,
    fetch_events,
    get_primary_calendar_meta,
    patch_event as google_patch_event,
)
from app.integrations.google.dto import GoogleEventDTO
from app.integrations.google.oauth_server import OAuthCallbackServer, OAuthServerConfig

logger = logging.getLogger("time-agent.gcal")


@dataclass(frozen=True)
class ConnectionStatusDTO:
    connected: bool
    auth_url: Optional[str] = None


@dataclass(frozen=True)
class ExternalSyncResultDTO:
    success: bool
    provider: str
    external_id: Optional[str] = None
    external_calendar_id: Optional[str] = None
    error_message: Optional[str] = None


class GoogleCalendarService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        bot_notify_fn: Callable[[int, str], Awaitable[None]],
    ):
        self._session_factory = session_factory
        self._bot_notify_fn = bot_notify_fn
        self._oauth_server: Optional[OAuthCallbackServer] = None

    async def is_connected(self) -> bool:
        creds = load_credentials()
        if not creds:
            return False

        creds = refresh_if_needed(creds)
        return bool(creds and creds.valid)

    async def get_auth_url_and_start_server(self, user_id: int) -> ConnectionStatusDTO:
        if await self.is_connected():
            return ConnectionStatusDTO(connected=True)

        code_verifier = secrets.token_urlsafe(64)

        async with self._session_factory() as session:
            repo = OAuthStateRepo(session)
            state = await repo.create_state(
                user_id=user_id,
                code_verifier=code_verifier,
                ttl_minutes=10,
            )

        await self._ensure_oauth_server_running()

        flow = build_flow(state=state)
        flow.code_verifier = code_verifier

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        logger.info("OAuth URL generated for user_id=%s", user_id)

        return ConnectionStatusDTO(
            connected=False,
            auth_url=auth_url,
        )

    async def _ensure_oauth_server_running(self) -> None:
        if self._oauth_server and self._oauth_server.is_running:
            return

        bind_host = os.getenv("GCAL_OAUTH_BIND_HOST", "0.0.0.0")
        port = int(os.getenv("GCAL_OAUTH_PORT", "8085"))
        timeout_sec = int(os.getenv("GCAL_OAUTH_TIMEOUT_SEC", "300"))

        cfg = OAuthServerConfig(
            bind_host=bind_host,
            port=port,
            timeout_sec=timeout_sec,
        )

        async def consume_state(state: str) -> tuple[int, str] | None:
            async with self._session_factory() as session:
                repo = OAuthStateRepo(session)
                return await repo.consume_state_by_state(state)

        async def on_success(user_id: int) -> None:
            await self._bot_notify_fn(user_id, "Google Calendar подключен ✅")
            logger.info("OAuth completed for user_id=%s", user_id)

        self._oauth_server = OAuthCallbackServer(
            config=cfg,
            consume_state_fn=consume_state,
            on_success_fn=on_success,
        )

        await self._oauth_server.start_once()

    async def get_today_events(self) -> list[dict[str, Any]]:
        """
        Получает события Google Calendar за сегодняшний день.
        """
        creds = load_credentials()

        if not creds:
            raise RuntimeError("Google credentials not found. Run /gcal_connect first.")

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            raise RuntimeError(
                "Google credentials invalid. Reconnect using /gcal_connect"
            )

        now = now_tz()

        day_start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=APP_TZ,
        )

        day_end = datetime.combine(
            now.date(),
            time.max,
            tzinfo=APP_TZ,
        )

        raw_events = fetch_events(day_start, day_end)

        result: list[dict[str, Any]] = []

        for event in raw_events:
            start_raw = event.get("start", {})
            end_raw = event.get("end", {})

            start_value = start_raw.get("dateTime") or start_raw.get("date")
            end_value = end_raw.get("dateTime") or end_raw.get("date")

            result.append(
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "(no title)"),
                    "start": start_value,
                    "end": end_value,
                    "html_link": event.get("htmlLink"),
                    "status": event.get("status"),
                }
            )

        return result

    async def list_events(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str = "primary",
    ) -> list[GoogleEventDTO]:
        creds = load_credentials()

        if not creds:
            raise RuntimeError("Google credentials not found. Run /gcal_connect first.")

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            raise RuntimeError(
                "Google credentials invalid. Reconnect using /gcal_connect"
            )

        raw_events = fetch_events(
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
        )

        result: list[GoogleEventDTO] = []
        for raw in raw_events:
            dto = self._map_raw_event(raw, calendar_id=calendar_id)
            if dto is not None:
                result.append(dto)

        return result

    async def get_debug_info(self) -> dict[str, Any]:
        """
        Возвращает диагностическую информацию по подключенному Google Calendar.
        """
        creds = load_credentials()

        if not creds:
            raise RuntimeError("Google credentials not found. Run /gcal_connect first.")

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            raise RuntimeError(
                "Google credentials invalid. Reconnect using /gcal_connect"
            )

        now = now_tz()

        day_start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=APP_TZ,
        )

        day_end = datetime.combine(
            now.date(),
            time.max,
            tzinfo=APP_TZ,
        )

        meta = get_primary_calendar_meta()
        events = fetch_events(day_start, day_end)

        return {
            "app_tz": APP_TZ.key,
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
            "calendar_id": meta.get("id"),
            "calendar_summary": meta.get("summary"),
            "calendar_time_zone": meta.get("timeZone"),
            "events_count": len(events),
        }

    async def create_event(
        self,
        *,
        task_id: int,
        title: str,
        start_at: datetime,
        duration_min: int,
        category: str = "personal",
        description: str = "",
        calendar_id: str = "primary",
    ) -> ExternalSyncResultDTO:
        """
        Создаёт событие в Google Calendar для локальной задачи.
        """
        creds = load_credentials()

        if not creds:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials not found. Run /gcal_connect first.",
            )

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials invalid. Reconnect using /gcal_connect",
            )

        try:
            end_at = start_at + timedelta(minutes=duration_min)

            created = google_create_event(
                summary=title,
                start_at=start_at,
                end_at=end_at,
                description=description,
                calendar_id=calendar_id,
                local_task_id=task_id,
                category=category,
            )

            return ExternalSyncResultDTO(
                success=True,
                provider="google_calendar",
                external_id=created.get("id"),
                external_calendar_id=calendar_id,
                error_message=None,
            )

        except Exception as e:
            logger.exception("Google create_event failed for task_id=%s", task_id)

            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message=str(e)[:500],
            )

    async def update_event(
        self,
        *,
        task_id: int,
        external_id: str,
        title: str,
        start_at: datetime,
        duration_min: int,
        category: str = "work",
        description: str = "",
        calendar_id: str = "primary",
    ) -> ExternalSyncResultDTO:
        creds = load_credentials()

        if not creds:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials not found. Run /gcal_connect first.",
            )

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials invalid. Reconnect using /gcal_connect",
            )

        try:
            end_at = start_at + timedelta(minutes=duration_min)

            updated = google_patch_event(
                calendar_id=calendar_id,
                event_id=external_id,
                summary=title,
                start_at=start_at,
                end_at=end_at,
                description=description,
                local_task_id=task_id,
                category=category,
            )

            return ExternalSyncResultDTO(
                success=True,
                provider="google_calendar",
                external_id=updated.get("id"),
                external_calendar_id=calendar_id,
                error_message=None,
            )

        except Exception as e:
            logger.exception(
                "Google update_event failed for task_id=%s external_id=%s",
                task_id,
                external_id,
            )
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message=str(e)[:500],
            )

    async def delete_event(
        self,
        *,
        external_id: str,
        calendar_id: str = "primary",
    ) -> ExternalSyncResultDTO:
        creds = load_credentials()

        if not creds:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials not found. Run /gcal_connect first.",
            )

        creds = refresh_if_needed(creds)

        if not creds or not creds.valid:
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message="Google credentials invalid. Reconnect using /gcal_connect",
            )

        try:
            google_delete_event(
                calendar_id=calendar_id,
                event_id=external_id,
            )

            return ExternalSyncResultDTO(
                success=True,
                provider="google_calendar",
                external_id=external_id,
                external_calendar_id=calendar_id,
                error_message=None,
            )

        except Exception as e:
            logger.exception(
                "Google delete_event failed for external_id=%s calendar_id=%s",
                external_id,
                calendar_id,
            )
            return ExternalSyncResultDTO(
                success=False,
                provider="google_calendar",
                error_message=str(e)[:500],
            )

    def _map_raw_event(
        self,
        raw: dict[str, Any],
        *,
        calendar_id: str,
    ) -> GoogleEventDTO | None:
        external_id = raw.get("id")
        if not external_id:
            return None

        start_raw = raw.get("start", {})
        end_raw = raw.get("end", {})

        start_value = start_raw.get("dateTime")
        end_value = end_raw.get("dateTime")

        all_day = False
        if start_value is None and start_raw.get("date") is not None:
            all_day = True
        if end_value is None and end_raw.get("date") is not None:
            all_day = True

        start_at = self._parse_google_datetime(start_value)
        end_at = self._parse_google_datetime(end_value)
        updated_at = self._parse_google_datetime(raw.get("updated"))

        extended_private = raw.get("extendedProperties", {}).get("private", {}) or {}
        local_task_id_raw = extended_private.get("local_task_id")

        local_task_id: int | None = None
        if local_task_id_raw is not None:
            try:
                local_task_id = int(local_task_id_raw)
            except (TypeError, ValueError):
                local_task_id = None

        return GoogleEventDTO(
            external_id=external_id,
            calendar_id=calendar_id,
            summary=raw.get("summary", "(no title)"),
            description=raw.get("description", "") or "",
            start_at=start_at,
            end_at=end_at,
            all_day=all_day,
            status=raw.get("status", "confirmed"),
            updated_at=updated_at,
            html_link=raw.get("htmlLink"),
            local_task_id=local_task_id,
            source_marker=extended_private.get("source"),
        )

    @staticmethod
    def _parse_google_datetime(value: str | None) -> datetime | None:
        if not value:
            return None

        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=APP_TZ)
        return dt.astimezone(APP_TZ)
