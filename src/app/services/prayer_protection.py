from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from app.core.time import APP_TZ
from app.services.prayer_times_service import PrayerTimesDTO


PRAYER_BUFFER_BEFORE_MIN = 15
PRAYER_BLOCK_AFTER_MIN = 20
PRAYER_SUGGESTION_BUFFER_MIN = 20

DHUHR_DEAD_ZONE_START = time(13, 0)
DHUHR_DEAD_ZONE_END = time(13, 20)
DHUHR_DEAD_ZONE_SHIFT_TO = time(13, 25)


@dataclass(frozen=True, slots=True)
class PrayerProtectedWindow:
    prayer_name: str
    start: datetime
    end: datetime


def iter_prayer_protected_windows(
    *,
    day: date,
    prayer_times: PrayerTimesDTO,
) -> Iterable[PrayerProtectedWindow]:
    for prayer_name, prayer_time in _iter_prayer_points(prayer_times):
        prayer_at = datetime.combine(day, prayer_time, tzinfo=APP_TZ)
        yield PrayerProtectedWindow(
            prayer_name=prayer_name,
            start=prayer_at - timedelta(minutes=PRAYER_BUFFER_BEFORE_MIN),
            end=prayer_at + timedelta(minutes=PRAYER_BLOCK_AFTER_MIN),
        )


def is_dhuhr_dead_zone_overlap(
    *,
    start_at: datetime,
    end_at: datetime,
    day: date,
) -> bool:
    dead_zone_start, dead_zone_end = build_dhuhr_dead_zone(day=day)
    return intervals_overlap(start_at, end_at, dead_zone_start, dead_zone_end)


def build_dhuhr_dead_zone(*, day: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, DHUHR_DEAD_ZONE_START, tzinfo=APP_TZ),
        datetime.combine(day, DHUHR_DEAD_ZONE_END, tzinfo=APP_TZ),
    )


def build_dhuhr_shift_start(*, day: date) -> datetime:
    return datetime.combine(day, DHUHR_DEAD_ZONE_SHIFT_TO, tzinfo=APP_TZ)


def intervals_overlap(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    return start_a < end_b and start_b < end_a


def _iter_prayer_points(prayer_times: PrayerTimesDTO):
    return [
        ("Fajr", prayer_times.fajr),
        ("Dhuhr", prayer_times.dhuhr),
        ("Asr", prayer_times.asr),
        ("Maghrib", prayer_times.maghrib),
        ("Isha", prayer_times.isha),
    ]
