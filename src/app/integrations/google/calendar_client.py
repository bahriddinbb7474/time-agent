from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.time import APP_TZ
from app.integrations.google.auth import load_credentials, refresh_if_needed

logger = logging.getLogger("time-agent.gcal")


def build_google_service():
    """
    Создаёт Google Calendar API client.
    """
    creds = load_credentials()

    if creds is None:
        raise RuntimeError("Google credentials not found. Run /gcal_connect first.")

    creds = refresh_if_needed(creds)

    if creds is None or not creds.valid:
        raise RuntimeError(
            "Google credentials are invalid. Reconnect with /gcal_connect."
        )

    service = build(
        "calendar",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )
    return service


def get_primary_calendar_meta() -> dict[str, Any]:
    """
    Возвращает информацию о primary calendar.
    """
    service = build_google_service()

    meta = service.calendars().get(calendarId="primary").execute()

    logger.info(
        "Primary calendar meta loaded: id=%s summary=%s timeZone=%s",
        meta.get("id"),
        meta.get("summary"),
        meta.get("timeZone"),
    )

    return meta


def fetch_events(
    time_min: datetime,
    time_max: datetime,
    calendar_id: str = "primary",
) -> list[dict[str, Any]]:
    """
    Получает события из Google Calendar в указанном интервале.
    """
    service = build_google_service()

    logger.info(
        "Fetching Google events: calendar_id=%s time_min=%s time_max=%s tz=%s",
        calendar_id,
        time_min.isoformat(),
        time_max.isoformat(),
        APP_TZ.key,
    )

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            timeZone=APP_TZ.key,
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )

    items = events_result.get("items", [])

    logger.info("Google Calendar returned %s events", len(items))

    for idx, item in enumerate(items, start=1):
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        logger.info(
            "Event #%s: id=%s summary=%s start=%s end=%s",
            idx,
            item.get("id"),
            item.get("summary"),
            start_raw.get("dateTime") or start_raw.get("date"),
            end_raw.get("dateTime") or end_raw.get("date"),
        )

    return items


def _build_event_body(
    *,
    summary: str,
    start_at: datetime,
    end_at: datetime,
    description: str = "",
    local_task_id: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    extended_private: dict[str, str] = {
        "source": "telegram_time_agent",
    }

    if local_task_id is not None:
        extended_private["local_task_id"] = str(local_task_id)

    if category:
        extended_private["category"] = category

    return {
        "summary": summary,
        "description": description,
        "start": {
            "dateTime": start_at.isoformat(),
            "timeZone": APP_TZ.key,
        },
        "end": {
            "dateTime": end_at.isoformat(),
            "timeZone": APP_TZ.key,
        },
        "extendedProperties": {
            "private": extended_private,
        },
    }


def create_event(
    *,
    summary: str,
    start_at: datetime,
    end_at: datetime,
    description: str = "",
    calendar_id: str = "primary",
    local_task_id: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """
    Создаёт событие в Google Calendar.
    """
    service = build_google_service()

    body = _build_event_body(
        summary=summary,
        start_at=start_at,
        end_at=end_at,
        description=description,
        local_task_id=local_task_id,
        category=category,
    )

    logger.info(
        "Creating Google event: calendar_id=%s summary=%s start=%s end=%s local_task_id=%s category=%s",
        calendar_id,
        summary,
        start_at.isoformat(),
        end_at.isoformat(),
        local_task_id,
        category,
    )

    created = (
        service.events()
        .insert(
            calendarId=calendar_id,
            body=body,
        )
        .execute()
    )

    logger.info(
        "Google event created: id=%s calendar_id=%s htmlLink=%s status=%s",
        created.get("id"),
        calendar_id,
        created.get("htmlLink"),
        created.get("status"),
    )

    return created


def patch_event(
    *,
    calendar_id: str,
    event_id: str,
    summary: str,
    start_at: datetime,
    end_at: datetime,
    description: str = "",
    local_task_id: int | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """
    PATCH-обновление события в Google Calendar.
    """
    service = build_google_service()

    body = _build_event_body(
        summary=summary,
        start_at=start_at,
        end_at=end_at,
        description=description,
        local_task_id=local_task_id,
        category=category,
    )

    logger.info(
        "Patching Google event: calendar_id=%s event_id=%s summary=%s start=%s end=%s",
        calendar_id,
        event_id,
        summary,
        start_at.isoformat(),
        end_at.isoformat(),
    )

    updated = (
        service.events()
        .patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=body,
        )
        .execute()
    )

    logger.info(
        "Google event patched: id=%s calendar_id=%s status=%s",
        updated.get("id"),
        calendar_id,
        updated.get("status"),
    )

    return updated


def delete_event(
    *,
    calendar_id: str,
    event_id: str,
) -> bool:
    """
    Удаляет событие из Google Calendar.
    Возвращает True даже при 404, чтобы delete был идемпотентным.
    """
    service = build_google_service()

    logger.info(
        "Deleting Google event: calendar_id=%s event_id=%s",
        calendar_id,
        event_id,
    )

    try:
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()

        logger.info(
            "Google event deleted: calendar_id=%s event_id=%s",
            calendar_id,
            event_id,
        )
        return True

    except HttpError as e:
        if getattr(e, "resp", None) is not None and e.resp.status == 404:
            logger.info(
                "Google event already absent (404 treated as success): calendar_id=%s event_id=%s",
                calendar_id,
                event_id,
            )
            return True
        raise
