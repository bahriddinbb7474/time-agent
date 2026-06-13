import asyncio
import os
import tempfile
import unittest.mock as mock
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiohttp

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

windows_zoneinfo = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and windows_zoneinfo.exists():
    os.environ["PYTHONTZPATH"] = str(windows_zoneinfo)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.time import APP_TZ
from app.db.models import Base, PrayerTime
from app.services.prayer_times_service import (
    PrayerApiUnavailableError,
    PrayerTimesDTO,
    PrayerTimesService,
    _MAX_ATTEMPTS,
)


def _make_http_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=status,
    )


async def _make_db():
    tmp = tempfile.TemporaryDirectory(prefix="time_agent_prayer_retry_")
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


async def _insert_prayer_row(session, target_date: date) -> None:
    row = PrayerTime(
        date=target_date,
        fajr=time(5, 0, tzinfo=APP_TZ),
        dhuhr=time(12, 30, tzinfo=APP_TZ),
        asr=time(15, 0, tzinfo=APP_TZ),
        maghrib=time(18, 30, tzinfo=APP_TZ),
        isha=time(20, 0, tzinfo=APP_TZ),
        created_at=datetime.now(APP_TZ),
    )
    session.add(row)
    await session.commit()


def _clear_month_key(*dates: date) -> None:
    for d in dates:
        PrayerTimesService._REFRESHED_MONTH_KEYS.discard((d.year, d.month))


# ── Test 1: Timeout → retry bounded → exact cache found → data returned ──────

async def test_timeout_retry_then_cache_fallback() -> None:
    """asyncio.TimeoutError triggers exactly _MAX_ATTEMPTS attempts; cached row returned."""
    target_date = date(2020, 1, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, target_date)

        attempt_count = 0

        async def always_timeout(self_inner, d):
            nonlocal attempt_count
            attempt_count += 1
            raise asyncio.TimeoutError("Aladhan timeout")

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_timeout):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    result = await service.get_prayer_times(target_date)

        assert result.date == target_date, f"Expected {target_date}, got {result.date}"
        assert attempt_count == _MAX_ATTEMPTS, (
            f"Expected {_MAX_ATTEMPTS} attempts, got {attempt_count}"
        )
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 2: HTTP 502 → retry bounded → exact cache found ─────────────────────

async def test_http_502_retry_then_cache_fallback() -> None:
    """HTTP 502 triggers _MAX_ATTEMPTS retries; exact cached row returned."""
    target_date = date(2020, 2, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, target_date)

        attempt_count = 0

        async def always_502(self_inner, d):
            nonlocal attempt_count
            attempt_count += 1
            raise _make_http_error(502)

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_502):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    result = await service.get_prayer_times(target_date)

        assert result.date == target_date
        assert attempt_count == _MAX_ATTEMPTS
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 3: HTTP 429 → retry is performed ────────────────────────────────────

async def test_http_429_triggers_retry() -> None:
    """HTTP 429 is a retryable status; more than 1 attempt must occur."""
    target_date = date(2020, 3, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, target_date)

        attempt_count = 0

        async def always_429(self_inner, d):
            nonlocal attempt_count
            attempt_count += 1
            raise _make_http_error(429)

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_429):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    await service.get_prayer_times(target_date)

        assert attempt_count > 1, (
            f"Expected retry on HTTP 429, got only {attempt_count} attempt(s)"
        )
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 4: HTTP 400 → retry NOT performed (1 attempt only) ──────────────────

async def test_http_400_does_not_retry() -> None:
    """HTTP 400 is non-retryable; exactly 1 attempt must be made."""
    target_date = date(2020, 4, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        attempt_count = 0

        async def always_400(self_inner, d):
            nonlocal attempt_count
            attempt_count += 1
            raise _make_http_error(400)

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_400):
                try:
                    await service.get_prayer_times(target_date)
                except (aiohttp.ClientResponseError, PrayerApiUnavailableError):
                    pass  # Either is acceptable; we only care about attempt count

        assert attempt_count == 1, (
            f"Expected exactly 1 attempt for HTTP 400, got {attempt_count}"
        )
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 5: No cache after all retries → PrayerApiUnavailableError ────────────

async def test_no_cache_after_retries_raises_unavailable() -> None:
    """All retries exhausted and no local cache → PrayerApiUnavailableError."""
    target_date = date(2020, 5, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        async def always_fail(self_inner, d):
            raise asyncio.TimeoutError("timeout")

        raised = False
        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_fail):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    try:
                        await service.get_prayer_times(target_date)
                    except PrayerApiUnavailableError as exc:
                        raised = True
                        assert target_date.isoformat() in str(exc), (
                            f"Error message missing date: {exc}"
                        )

        assert raised, "Expected PrayerApiUnavailableError but nothing was raised"
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 6: Cache for wrong month → not used ─────────────────────────────────

async def test_wrong_month_cache_not_used() -> None:
    """Only July 2020 cached; request for June 2020 → PrayerApiUnavailableError."""
    target_date = date(2020, 6, 15)
    wrong_date = date(2020, 7, 15)
    _clear_month_key(target_date, wrong_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, wrong_date)  # only July cached

        async def always_fail(self_inner, d):
            raise asyncio.TimeoutError("timeout")

        raised = False
        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_fail):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    try:
                        await service.get_prayer_times(target_date)
                    except PrayerApiUnavailableError:
                        raised = True

        assert raised, "Wrong-month cache must not be used as fallback"
    finally:
        _clear_month_key(target_date, wrong_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 7: Cache from wrong year → not used ─────────────────────────────────

async def test_wrong_year_cache_not_used() -> None:
    """
    Only 2019-08-15 in cache; request for 2020-08-15 → PrayerApiUnavailableError.

    City, country, method, school are class-level constants that cannot change at
    runtime; year+month are the checkable discriminators.  A stale cache from a
    previous year (which would correspond to a different physical config if the
    service were ever reconfigured) must not be served.
    """
    target_date = date(2020, 8, 15)
    wrong_year_date = date(2019, 8, 15)
    _clear_month_key(target_date, wrong_year_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, wrong_year_date)  # 2019, not 2020

        async def always_fail(self_inner, d):
            raise asyncio.TimeoutError("timeout")

        raised = False
        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", always_fail):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    try:
                        await service.get_prayer_times(target_date)
                    except PrayerApiUnavailableError:
                        raised = True

        assert raised, "Wrong-year cache must not be used as fallback"
    finally:
        _clear_month_key(target_date, wrong_year_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 8: Successful API → normal path, cache updated ──────────────────────

async def test_successful_api_normal_path_and_cache_update() -> None:
    """Successful fetch_month → result returned, month key added to _REFRESHED_MONTH_KEYS."""
    target_date = date(2020, 9, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        fake_dto = PrayerTimesDTO(
            date=target_date,
            fajr=time(5, 10, tzinfo=APP_TZ),
            dhuhr=time(12, 35, tzinfo=APP_TZ),
            asr=time(15, 15, tzinfo=APP_TZ),
            maghrib=time(18, 40, tzinfo=APP_TZ),
            isha=time(20, 10, tzinfo=APP_TZ),
        )

        async def success_fetch(self_inner, d):
            return [fake_dto]

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", success_fetch):
                result = await service.get_prayer_times(target_date)

        assert result.date == target_date
        assert result.fajr == fake_dto.fajr
        assert (target_date.year, target_date.month) in PrayerTimesService._REFRESHED_MONTH_KEYS
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Test 9: Attempt count never exceeds _MAX_ATTEMPTS ────────────────────────

async def test_attempt_count_never_exceeds_max() -> None:
    """fetch_month is called at most _MAX_ATTEMPTS times regardless of failure type."""
    target_date = date(2020, 10, 15)
    _clear_month_key(target_date)
    tmp, engine, Session = await _make_db()
    try:
        async with Session() as session:
            await _insert_prayer_row(session, target_date)

        call_count = 0

        async def counting_fail(self_inner, d):
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError("timeout")

        async with Session() as session:
            service = PrayerTimesService(session)
            with mock.patch.object(PrayerTimesService, "fetch_month", counting_fail):
                with mock.patch.object(asyncio, "sleep", AsyncMock()):
                    await service.get_prayer_times(target_date)

        assert call_count == _MAX_ATTEMPTS, (
            f"Expected exactly {_MAX_ATTEMPTS} attempts, got {call_count}"
        )
    finally:
        _clear_month_key(target_date)
        await engine.dispose()
        tmp.cleanup()


# ── Runner ────────────────────────────────────────────────────────────────────

async def main_async() -> None:
    await test_timeout_retry_then_cache_fallback()
    await test_http_502_retry_then_cache_fallback()
    await test_http_429_triggers_retry()
    await test_http_400_does_not_retry()
    await test_no_cache_after_retries_raises_unavailable()
    await test_wrong_month_cache_not_used()
    await test_wrong_year_cache_not_used()
    await test_successful_api_normal_path_and_cache_update()
    await test_attempt_count_never_exceeds_max()


def main() -> None:
    asyncio.run(main_async())
    print(
        "PASS: prayer API retry bounded, cache fallback exact-match, "
        "no retry on 4xx, attempt count capped"
    )


if __name__ == "__main__":
    main()
