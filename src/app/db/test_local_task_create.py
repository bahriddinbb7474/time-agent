import asyncio
import os
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import APP_TZ
from app.db.models import AlertQueue, Base, PrayerTime
from app.services.task_create_service import TaskCreateService
from app.services.validation_result import ValidationStatus


def _at(target_date: date, hour: int, minute: int) -> datetime:
    return datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=APP_TZ)


async def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "local_task_create_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with Session() as session:
                service = TaskCreateService(session)

                # 1. Create task without time — must succeed
                result = await service.create_task(
                    title="Позвонить маме",
                    planned_at=None,
                    duration_min=20,
                    category="personal",
                    user_id=123456789,
                )
                assert result.local_created is True, f"Expected local_created=True: {result}"
                assert result.task is not None
                assert result.task.title == "Позвонить маме"
                assert result.task.category == "personal"
                # validation_result may be VALID (not None) — that's correct
                assert (
                    result.validation_result is None
                    or result.validation_result.status == ValidationStatus.VALID
                )
                task_id = result.task.id

                # 2. Update the task
                update_result = await service.update_task(
                    task_id=task_id,
                    title="Позвонить маме завтра",
                    planned_at=None,
                    duration_min=30,
                    category="personal",
                    user_id=123456789,
                )
                assert update_result.local_updated is True
                assert update_result.task is not None
                assert update_result.task.title == "Позвонить маме завтра"

                # 3. Delete the task
                delete_result = await service.delete_task(task_id=task_id)
                assert delete_result.local_deleted is True
                assert delete_result.task_id == task_id

                # 4. Delete non-existent task
                missing_delete = await service.delete_task(task_id=99999)
                assert missing_delete.local_deleted is False
                assert "не найдена" in missing_delete.user_message

                # 5. Prayer protection: seed prayer times and check conflict
                target_day = datetime.now(APP_TZ).date() + timedelta(days=1)
                session.add(
                    PrayerTime(
                        date=target_day,
                        fajr=time(5, 0, tzinfo=APP_TZ),
                        dhuhr=time(12, 30, tzinfo=APP_TZ),
                        asr=time(15, 0, tzinfo=APP_TZ),
                        maghrib=time(18, 30, tzinfo=APP_TZ),
                        isha=time(20, 0, tzinfo=APP_TZ),
                        created_at=datetime.now(APP_TZ),
                    )
                )
                await session.commit()

                # Dhuhr dead zone 13:05 must block creation
                prayer_block_result = await service.create_task(
                    title="Встреча",
                    planned_at=_at(target_day, 13, 5),
                    duration_min=30,
                    category="work",
                )
                assert prayer_block_result.local_created is False, (
                    f"Prayer protection did not block: {prayer_block_result}"
                )
                assert prayer_block_result.validation_result is not None
                assert prayer_block_result.validation_result.status != ValidationStatus.VALID

                # 6. Boss task creates AlertQueue record
                boss_result = await service.create_task(
                    title="🔥 Срочно сдать отчет",
                    planned_at=None,
                    duration_min=60,
                    category="work",
                    user_id=123456789,
                )
                assert boss_result.local_created is True
                assert boss_result.task is not None
                boss_task_id = boss_result.task.id
                assert "Boss alert" in boss_result.user_message or "boss" in boss_result.user_message.lower()

                alerts = (
                    await session.execute(
                        select(AlertQueue).where(
                            AlertQueue.alert_type == "boss_critical",
                            AlertQueue.entity_type == "task",
                            AlertQueue.entity_id == str(boss_task_id),
                        )
                    )
                ).scalars().all()
                assert len(alerts) >= 1, f"Expected boss alert, got {len(alerts)}"
                assert alerts[0].status == "pending"

                # 7. Delete boss task — cleanup runs without error
                delete_boss = await service.delete_task(task_id=boss_task_id)
                assert delete_boss.local_deleted is True

                # 8. Verify no GoogleCalendarService in active module-level namespace
                import app.services.task_create_service as tcs_mod
                import app.services.capture_action_service as cas_mod
                import app.handlers.add as add_mod
                import app.handlers.task_lifecycle as lifecycle_mod
                import app.services.capture_router_service as crs_mod

                for mod in (tcs_mod, cas_mod, add_mod, lifecycle_mod, crs_mod):
                    assert "GoogleCalendarService" not in dir(mod), (
                        f"GoogleCalendarService found in {mod.__name__}"
                    )
                    assert "TaskSyncService" not in dir(mod), (
                        f"TaskSyncService found in {mod.__name__}"
                    )

        finally:
            await engine.dispose()

    print("PASS: local task create service — invariants verified")


if __name__ == "__main__":
    asyncio.run(main())
