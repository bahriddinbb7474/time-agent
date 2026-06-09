from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.time import APP_TZ
from app.integrations.google.dto import GoogleEventDTO


@dataclass(slots=True)
class FakeWriteService:
    create_calls: int = 0
    update_calls: int = 0
    delete_calls: int = 0

    async def create_event(self, **_kwargs):
        self.create_calls += 1

    async def update_event(self, **_kwargs):
        self.update_calls += 1

    async def delete_event(self, **_kwargs):
        self.delete_calls += 1


async def _maybe_write_when_enabled(*, writes_enabled: bool, service: FakeWriteService) -> None:
    if not writes_enabled:
        return

    await service.create_event()
    await service.update_event()
    await service.delete_event()


def _safe_line(event: GoogleEventDTO) -> str | None:
    if event.status == "cancelled":
        return None

    if event.all_day:
        return f"• весь день — {event.summary}"

    if event.start_at is None:
        return f"• {event.summary}"

    return f"• {event.start_at.astimezone(APP_TZ).strftime('%H:%M')} — {event.summary}"


async def main():
    start_at = datetime(2026, 6, 9, 9, 30, tzinfo=APP_TZ)
    end_at = start_at + timedelta(minutes=30)

    timed = GoogleEventDTO(
        external_id="secret-event-id",
        calendar_id="primary",
        summary="Daily sync",
        description="",
        start_at=start_at,
        end_at=end_at,
        all_day=False,
        status="confirmed",
        updated_at=None,
        html_link="https://calendar.example/private",
        local_task_id=None,
        source_marker=None,
    )
    all_day = GoogleEventDTO(
        external_id="all-day-secret-id",
        calendar_id="primary",
        summary="Conference day",
        description="",
        start_at=None,
        end_at=None,
        all_day=True,
        status="confirmed",
        updated_at=None,
        html_link=None,
        local_task_id=None,
        source_marker=None,
    )
    cancelled = GoogleEventDTO(
        external_id="cancelled-secret-id",
        calendar_id="primary",
        summary="Cancelled call",
        description="",
        start_at=start_at,
        end_at=end_at,
        all_day=False,
        status="cancelled",
        updated_at=None,
        html_link=None,
        local_task_id=None,
        source_marker=None,
    )

    lines = [line for line in (_safe_line(timed), _safe_line(all_day), _safe_line(cancelled)) if line]

    assert lines == [
        "• 09:30 — Daily sync",
        "• весь день — Conference day",
    ]
    rendered = "\n".join(lines)
    assert "secret-event-id" not in rendered
    assert "calendar.example" not in rendered
    assert "primary" not in rendered

    fake_service = FakeWriteService()
    await _maybe_write_when_enabled(writes_enabled=False, service=fake_service)
    assert fake_service.create_calls == 0
    assert fake_service.update_calls == 0
    assert fake_service.delete_calls == 0

    print("PASS: Google read-first smoke test uses fake data only")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
