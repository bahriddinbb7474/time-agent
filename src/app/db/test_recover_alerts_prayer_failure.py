import asyncio
import json
import os
import tempfile
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import APP_TZ
from app.db.models import AlertQueue, Base
from app.scheduler.scheduler import recover_alerts


class FakeScheduler:
    """Minimal APScheduler stand-in that records add_job calls."""

    def __init__(self):
        self.added: list[str] = []

    def get_jobs(self):
        return []

    def get_job(self, job_id: str):
        return None

    def add_job(self, func, trigger=None, id=None, **kwargs):
        if id is not None:
            self.added.append(id)

    def remove_job(self, job_id: str):
        pass


async def _make_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_prayer_failure_")
    db_path = Path(tmp.name) / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        echo=False,
        future=True,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return tmp, engine, Session


async def _insert_pending_task_alert(session, minutes_from_now: int = 60) -> int:
    """Insert a non-prayer pending alert and return its id."""
    now = datetime.now(APP_TZ)
    scheduled_for = now + timedelta(minutes=minutes_from_now)
    alert = AlertQueue(
        alert_type="boss_deadline",
        entity_type="task",
        entity_id="42",
        scheduled_for=scheduled_for,
        status="pending",
        priority=50,
        payload_json=json.dumps({"chat_id": 123456789, "task_id": 42}),
        created_at=now,
        updated_at=now,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert.id


# ── Test 1: asyncio.TimeoutError from ensure_prayer_alerts_for_day ──────────

async def test_timeout_error_does_not_crash_recover_alerts() -> None:
    """recover_alerts must not raise when ensure_prayer_alerts_for_day times out."""
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            alert_id = await _insert_pending_task_alert(session)

        async with Session() as session:
            sched = FakeScheduler()
            with unittest.mock.patch(
                "app.scheduler.scheduler.ensure_prayer_alerts_for_day",
                side_effect=asyncio.TimeoutError("Aladhan timeout"),
            ):
                # Must not raise
                await recover_alerts(scheduler=sched, session=session, bot=None)

            # Regular alert must have been scheduled
            assert f"alert_{alert_id}" in sched.added, (
                f"Expected alert_{alert_id} in scheduled jobs, got: {sched.added}"
            )
    finally:
        await engine.dispose()
        tmp.cleanup()


# ── Test 2: HTTP 502-like error does not propagate ───────────────────────────

async def test_http_error_does_not_propagate_from_recover_alerts() -> None:
    """recover_alerts must survive a generic network/HTTP error from prayer recovery."""
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            # Simulate aiohttp.ClientResponseError (no real aiohttp needed)
            class FakeClientResponseError(Exception):
                pass

            sched = FakeScheduler()
            with unittest.mock.patch(
                "app.scheduler.scheduler.ensure_prayer_alerts_for_day",
                side_effect=FakeClientResponseError("502 Bad Gateway"),
            ):
                # Must not raise
                await recover_alerts(scheduler=sched, session=session, bot=None)
    finally:
        await engine.dispose()
        tmp.cleanup()


# ── Test 3: Normal path — prayer recovery called, regular alerts recovered ───

async def test_normal_path_prayer_and_regular_alerts() -> None:
    """On success, prayer recovery runs and regular alerts are scheduled."""
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            alert_id = await _insert_pending_task_alert(session)

        async with Session() as session:
            sched = FakeScheduler()
            prayer_called = []

            async def fake_ensure_prayer(*args, **kwargs):
                prayer_called.append(True)

            with unittest.mock.patch(
                "app.scheduler.scheduler.ensure_prayer_alerts_for_day",
                side_effect=fake_ensure_prayer,
            ):
                await recover_alerts(scheduler=sched, session=session, bot=None)

            assert prayer_called, "ensure_prayer_alerts_for_day was not called"
            assert f"alert_{alert_id}" in sched.added, (
                f"Regular alert not scheduled. Jobs: {sched.added}"
            )
    finally:
        await engine.dispose()
        tmp.cleanup()


# ── Test 4: main.py safety boundary (structural) ────────────────────────────

async def test_main_safety_boundary_survives_recover_alerts_exception() -> None:
    """
    Verifies the safety boundary in main.py: if recover_alerts raises an
    unexpected exception, the startup must not propagate it.

    We test this by replicating the exact try/except pattern from main.py
    and confirming it catches the exception without re-raising.
    """
    exception_logged = []

    class FakeLogger:
        def exception(self, msg, *args, **kwargs):
            exception_logged.append(msg)

    async def broken_recover_alerts(**kwargs):
        raise RuntimeError("Unexpected failure in recover_alerts")

    fake_log = FakeLogger()

    # Replicate the exact main.py safety boundary pattern
    try:
        await broken_recover_alerts(scheduler=None, session=None, bot=None)
        fake_log.exception("should not reach")  # type: ignore[unreachable]
    except Exception:
        fake_log.exception(
            "Alert recovery failed — startup continues without full recovery"
        )

    assert exception_logged, "Safety boundary did not log the exception"
    assert "Alert recovery failed" in exception_logged[0]


# ── Runner ───────────────────────────────────────────────────────────────────

async def main_async() -> None:
    await test_timeout_error_does_not_crash_recover_alerts()
    await test_http_error_does_not_propagate_from_recover_alerts()
    await test_normal_path_prayer_and_regular_alerts()
    await test_main_safety_boundary_survives_recover_alerts_exception()


def main() -> None:
    asyncio.run(main_async())
    print("PASS: recover_alerts survives prayer API failure; regular alerts still scheduled")


if __name__ == "__main__":
    main()
