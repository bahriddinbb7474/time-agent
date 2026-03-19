from datetime import datetime, time
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Tashkent")


def now_tz() -> datetime:
    """Текущее время в TZ приложения"""
    return datetime.now(tz=APP_TZ)


def parse_time(value: str) -> time:
    """'12:30' → time"""
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute, tzinfo=APP_TZ)
