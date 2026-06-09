from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.core.time import APP_TZ
from app.integrations.google.dto import GoogleEventDTO
from app.services.task_sync_service import TaskSyncService
from app.services.google_event_formatter import (
    format_google_event_line,
    format_google_event_lines,
)


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


async def main():
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
    os.environ["ENABLE_GOOGLE_WRITES"] = "false"

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

    assert format_google_event_line(timed) == "• 09:30 — Daily sync"
    assert format_google_event_line(all_day) == "• весь день — Conference day"
    assert format_google_event_line(cancelled) is None

    lines = format_google_event_lines([timed, all_day, cancelled])

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

    with tempfile.TemporaryDirectory(prefix="time_agent_google_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "google_read_first.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            service = TaskSyncService(session=session, gcal_service=fake_service)
            result = await service.create_task_with_google_sync(
                title="Work sync test",
                planned_at=start_at,
                duration_min=30,
                category="work",
                skip_context_validation=True,
            )

            assert result.local_created is True
            assert result.google_sync_status == "google_writes_disabled"
            assert fake_service.create_calls == 0
            assert fake_service.update_calls == 0
            assert fake_service.delete_calls == 0

        await engine.dispose()

    print("PASS: Google read-first smoke test uses fake data only")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
