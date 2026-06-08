import asyncio
import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from app.core.time import APP_TZ
from app.db.models import AlertQueue, Base, PrayerTime
from app.services.context_validator import ContextValidator
from app.services.prayer_times_service import PrayerTimesDTO, PrayerTimesService
from app.services.validation_result import ConflictType, ValidationStatus


class FakeRoutineService:
    async def is_sleep_time(self, _dt):
        return False

    async def is_second_sleep(self, _dt):
        return False


class FakeRulesService:
    async def check_conflicts(self, planned_at, duration_min):
        return []


class FakePrayerTimesService:
    def __init__(self, session):
        self.session = session

    async def get_prayer_times(self, target_date):
        return PrayerTimesDTO(
            date=target_date,
            fajr=time(5, 0, tzinfo=APP_TZ),
            dhuhr=time(12, 30, tzinfo=APP_TZ),
            asr=time(15, 0, tzinfo=APP_TZ),
            maghrib=time(18, 30, tzinfo=APP_TZ),
            isha=time(20, 0, tzinfo=APP_TZ),
        )


class NoFetchPrayerTimesService(PrayerTimesService):
    async def fetch_month(self, target_date):
        raise AssertionError("validator should use cached prayer times")


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=APP_TZ)


async def main():
    assert PrayerTimesService.SCHOOL == 1
    assert str(APP_TZ) == "Asia/Tashkent"

    target_day = date(2026, 6, 9)

    with tempfile.TemporaryDirectory(prefix="time_agent_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "prayer_validation_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}",
            echo=False,
            future=True,
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            validator = ContextValidator(
                routine_service=FakeRoutineService(),
                prayer_times_service=FakePrayerTimesService(session),
                rules_service=FakeRulesService(),
            )

            asr_conflict = await validator.validate_event(
                start_at=at(target_day, 14, 50),
                duration_min=20,
            )
            assert asr_conflict.status == ValidationStatus.CONFLICT
            assert asr_conflict.conflict_type == ConflictType.PRAYER
            assert asr_conflict.reason_code == "prayer_conflict"
            assert asr_conflict.suggested_slot_start == at(target_day, 15, 45)

            dhuhr_conflict = await validator.validate_event(
                start_at=at(target_day, 13, 5),
                duration_min=10,
            )
            assert dhuhr_conflict.status == ValidationStatus.CONFLICT
            assert dhuhr_conflict.reason_code == "dhuhr_dead_zone"
            assert dhuhr_conflict.suggested_slot_start == at(target_day, 13, 25)

            session.add(
                AlertQueue(
                    alert_type="prayer_reminder",
                    entity_type="prayer",
                    entity_id=f"{target_day.isoformat()}:asr",
                    scheduled_for=at(target_day, 14, 50),
                    repeat_interval_min=15,
                    status="done",
                    priority=1000,
                    payload_json=None,
                    created_at=at(target_day, 14, 40),
                    updated_at=at(target_day, 15, 5),
                    completed_at=at(target_day, 15, 5),
                )
            )
            await session.commit()

            completed_asr_result = await validator.validate_event(
                start_at=at(target_day, 14, 50),
                duration_min=20,
            )
            assert completed_asr_result.status == ValidationStatus.VALID

            session.add(
                PrayerTime(
                    date=date(2026, 6, 10),
                    fajr=time(5, 0, tzinfo=APP_TZ),
                    dhuhr=time(12, 30, tzinfo=APP_TZ),
                    asr=time(15, 0, tzinfo=APP_TZ),
                    maghrib=time(18, 30, tzinfo=APP_TZ),
                    isha=time(20, 0, tzinfo=APP_TZ),
                    created_at=at(target_day, 4, 0),
                )
            )
            await session.commit()

            cached_validator = ContextValidator(
                routine_service=FakeRoutineService(),
                prayer_times_service=NoFetchPrayerTimesService(session),
                rules_service=FakeRulesService(),
            )
            cached_result = await cached_validator.validate_event(
                start_at=at(date(2026, 6, 10), 14, 50),
                duration_min=20,
            )
            assert cached_result.reason_code == "prayer_conflict"

            from app.scheduler.jobs import _resolve_prayer_quiet_until

            quiet_until = await _resolve_prayer_quiet_until(
                session=session,
                now=at(date(2026, 6, 10), 14, 50),
            )
            assert quiet_until == at(date(2026, 6, 10), 15, 21)

        await engine.dispose()

    print("PASS: Prayer validation uses isolated temp SQLite DB")


if __name__ == "__main__":
    asyncio.run(main())
