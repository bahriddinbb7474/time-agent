from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ
from app.db.models import PrayerTime


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
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
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

    async def get_prayer_times(self, target_date: date) -> PrayerTimesDTO:
        """
        Main read API for the app.

        Rule:
        - first request for a month forces refresh from API and overwrites cache rows
        - then read target day from local DB cache
        """
        month_key = (target_date.year, target_date.month)
        if month_key not in self._REFRESHED_MONTH_KEYS:
            month_rows = await self.fetch_month(target_date)
            await self.store_month(month_rows)
            self._REFRESHED_MONTH_KEYS.add(month_key)

        existing = await self._get_row_by_date(target_date)
        if existing is not None:
            return self._to_dto(existing)

        month_rows = await self.fetch_month(target_date)
        await self.store_month(month_rows)

        existing = await self._get_row_by_date(target_date)
        if existing is None:
            raise ValueError(
                f"Prayer times not found for date: {target_date.isoformat()}"
            )

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


