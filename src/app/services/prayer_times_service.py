from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import PrayerTime

log = logging.getLogger("time-agent.prayer")

_CONNECT_TIMEOUT = 3.0
_TOTAL_TIMEOUT = 8.0
_MAX_ATTEMPTS = 3
_RETRY_BACKOFFS = (2.0, 4.0)  # seconds between attempt pairs (1→2, 2→3)
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


class PrayerApiUnavailableError(RuntimeError):
    """Raised when Aladhan API fails and no exact local cache exists for the date."""


@dataclass(slots=True)
class PrayerTimesDTO:
    date: date
    fajr: time
    dhuhr: time
    asr: time
    maghrib: time
    isha: time


class PrayerTimesService:
    BASE_URL = "https://api.aladhan.com/v1"
    CITY = "Tashkent"
    COUNTRY = "Uzbekistan"
    METHOD = 3
    SCHOOL = 1  # Hanafi / Mithlayn
    _REFRESHED_MONTH_KEYS: set[tuple[int, int]] = set()

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def fetch_month(self, target_date: date) -> list[PrayerTimesDTO]:
        """
        Fetches prayer times for the whole month from Aladhan API.

        Endpoint:
            GET /calendarByCity
        """
        month = target_date.month
        year = target_date.year

        url = f"{self.BASE_URL}/calendarByCity"
        params = {
            "city": self.CITY,
            "country": self.COUNTRY,
            "method": str(self.METHOD),
            "school": str(self.SCHOOL),
            "month": str(month),
            "year": str(year),
        }

        async with aiohttp.ClientSession() as client:
            async with client.get(
                url,
                params=params,
                timeout=aiohttp.ClientTimeout(
                    total=_TOTAL_TIMEOUT, connect=_CONNECT_TIMEOUT
                ),
            ) as response:
                response.raise_for_status()
                payload: dict[str, Any] = await response.json()

        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Unexpected Aladhan response: 'data' is not a list")

        result: list[PrayerTimesDTO] = []

        for item in data:
            dto = self._map_calendar_item(item)
            if dto is not None:
                result.append(dto)

        return result

    async def store_month(self, rows: list[PrayerTimesDTO]) -> None:
        """
        Idempotent month storage:
        - inserts missing dates
        - updates existing dates
        """
        if not rows:
            return

        dates = [row.date for row in rows]

        stmt = select(PrayerTime).where(PrayerTime.date.in_(dates))
        existing_result = await self.session.execute(stmt)
        existing_rows = {row.date: row for row in existing_result.scalars().all()}

        now = datetime.now(APP_TZ)

        for row in rows:
            existing = existing_rows.get(row.date)

            if existing is None:
                self.session.add(
                    PrayerTime(
                        date=row.date,
                        fajr=row.fajr,
                        dhuhr=row.dhuhr,
                        asr=row.asr,
                        maghrib=row.maghrib,
                        isha=row.isha,
                        created_at=now,
                    )
                )
                continue

            existing.fajr = row.fajr
            existing.dhuhr = row.dhuhr
            existing.asr = row.asr
            existing.maghrib = row.maghrib
            existing.isha = row.isha

        await self.session.commit()

    async def _fetch_month_with_retry(self, target_date: date) -> list[PrayerTimesDTO]:
        """
        Calls fetch_month() with bounded retry.

        Retries on: asyncio.TimeoutError, connection errors, HTTP 429/5xx.
        Does NOT retry on: other HTTP 4xx, response validation errors (ValueError).
        Max attempts: _MAX_ATTEMPTS.  Worst-case wait: sum(_RETRY_BACKOFFS) + attempts*_TOTAL_TIMEOUT.
        """
        last_exc: BaseException | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self.fetch_month(target_date)
            except (
                asyncio.TimeoutError,
                aiohttp.ClientConnectorError,
                aiohttp.ServerConnectionError,
            ) as exc:
                last_exc = exc
                log.warning(
                    "Aladhan attempt %d/%d failed (network): %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    exc,
                )
            except aiohttp.ClientResponseError as exc:
                if exc.status in _RETRYABLE_HTTP_STATUSES:
                    last_exc = exc
                    log.warning(
                        "Aladhan attempt %d/%d failed (HTTP %s)",
                        attempt,
                        _MAX_ATTEMPTS,
                        exc.status,
                    )
                else:
                    log.warning(
                        "Aladhan non-retryable HTTP %s — not retrying", exc.status
                    )
                    raise

            if attempt < _MAX_ATTEMPTS:
                backoff = _RETRY_BACKOFFS[attempt - 1]
                log.info("Aladhan retry backoff %.1fs before attempt %d", backoff, attempt + 1)
                await asyncio.sleep(backoff)

        assert last_exc is not None
        raise last_exc

    async def get_prayer_times(self, target_date: date) -> PrayerTimesDTO:
        """
        Main read API for the app.

        Rule:
        - first request for a month forces refresh from API (with bounded retry) and overwrites cache rows
        - then read target day from local DB cache
        - if API unavailable after all retries: use exact cached row if present,
          otherwise raise PrayerApiUnavailableError
        """
        month_key = (target_date.year, target_date.month)
        if month_key not in self._REFRESHED_MONTH_KEYS:
            try:
                month_rows = await self._fetch_month_with_retry(target_date)
                await self.store_month(month_rows)
                self._REFRESHED_MONTH_KEYS.add(month_key)
            except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as fetch_exc:
                log.error(
                    "Aladhan API unavailable for %04d-%02d after all attempts: %s",
                    target_date.year,
                    target_date.month,
                    fetch_exc,
                )
                fallback = await self._get_cached_month_fallback(target_date)
                if fallback is not None:
                    log.info(
                        "Using exact cached fallback for %s (month key %s)",
                        target_date,
                        month_key,
                    )
                    return fallback
                log.error(
                    "No exact cached fallback for %s — raising PrayerApiUnavailableError",
                    target_date,
                )
                raise PrayerApiUnavailableError(
                    f"Prayer API unavailable and no local cache for {target_date.isoformat()}"
                ) from fetch_exc

        existing = await self._get_row_by_date(target_date)
        if existing is not None:
            return self._to_dto(existing)

        try:
            month_rows = await self._fetch_month_with_retry(target_date)
            await self.store_month(month_rows)
        except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as fetch_exc:
            log.error(
                "Aladhan API unavailable on second fetch for %s: %s",
                target_date,
                fetch_exc,
            )
            fallback = await self._get_cached_month_fallback(target_date)
            if fallback is not None:
                log.info(
                    "Using exact cached fallback for %s (second fetch path)", target_date
                )
                return fallback
            raise PrayerApiUnavailableError(
                f"Prayer API unavailable and no local cache for {target_date.isoformat()}"
            ) from fetch_exc

        existing = await self._get_row_by_date(target_date)
        if existing is None:
            raise ValueError(
                f"Prayer times not found for date: {target_date.isoformat()}"
            )

        return self._to_dto(existing)

    async def get_cached_prayer_times(
        self,
        target_date: date,
    ) -> PrayerTimesDTO | None:
        existing = await self._get_row_by_date(target_date)
        if existing is None:
            return None
        return self._to_dto(existing)

    async def _get_cached_month_fallback(
        self,
        target_date: date,
    ) -> PrayerTimesDTO | None:
        """
        Returns cached prayer times for the exact target_date if a DB row exists.

        Year and month are validated implicitly: the query uses the exact date, so only
        a row for that precise calendar day is returned.  City, country, calculation method,
        and school are class-level constants (CITY, COUNTRY, METHOD, SCHOOL) and cannot
        differ between the cached rows and the current service configuration at runtime.

        Returns None if no row exists for target_date (wrong month, wrong year, or never cached).
        """
        existing = await self._get_row_by_date(target_date)
        if existing is None:
            return None
        return self._to_dto(existing)

    async def _get_row_by_date(self, target_date: date) -> PrayerTime | None:
        stmt = select(PrayerTime).where(PrayerTime.date == target_date)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _to_dto(row: PrayerTime) -> PrayerTimesDTO:
        return PrayerTimesDTO(
            date=row.date,
            fajr=row.fajr,
            dhuhr=row.dhuhr,
            asr=row.asr,
            maghrib=row.maghrib,
            isha=row.isha,
        )

    def _map_calendar_item(self, item: dict[str, Any]) -> PrayerTimesDTO | None:
        """
        Expected Aladhan calendar item shape contains:
        - date.gregorian.date   -> e.g. '08-03-2026'
        - timings.Fajr
        - timings.Dhuhr
        - timings.Asr
        - timings.Maghrib
        - timings.Isha
        """
        date_block = item.get("date", {})
        gregorian_block = date_block.get("gregorian", {})
        date_str = gregorian_block.get("date")

        timings = item.get("timings", {})

        if not date_str:
            return None

        parsed_date = datetime.strptime(date_str, "%d-%m-%Y").date()

        return PrayerTimesDTO(
            date=parsed_date,
            fajr=self._parse_api_time(timings["Fajr"]),
            dhuhr=self._parse_api_time(timings["Dhuhr"]),
            asr=self._parse_api_time(timings["Asr"]),
            maghrib=self._parse_api_time(timings["Maghrib"]),
            isha=self._parse_api_time(timings["Isha"]),
        )

    @staticmethod
    def _parse_api_time(value: str) -> time:
        """
        Converts values like:
            '05:19 (+05)'
            '12:34'
        to Python time with APP_TZ.
        """
        hhmm = value.strip().split(" ")[0]
        hour_str, minute_str = hhmm.split(":")
        return time(
            hour=int(hour_str),
            minute=int(minute_str),
            tzinfo=APP_TZ,
        )


