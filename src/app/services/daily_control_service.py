from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.db.models import ActivityEntry, Checkin, DailySchedule, TimeBlock


SCHEDULE_STATUSES = frozenset({"draft", "confirmed", "archived"})
TIME_BLOCK_STATUSES = frozenset({"planned", "completed", "cancelled"})
CHECKIN_STATUSES = frozenset({"pending", "open", "answered", "deferred", "expired"})


class DailyControlError(Exception):
    pass


class DailyControlValidationError(DailyControlError):
    pass


class DailyControlNotFoundError(DailyControlError):
    pass


class DailyControlOverlapError(DailyControlValidationError):
    pass


def _aware_local(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DailyControlValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(APP_TZ)


def _valid_interval(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    start = _aware_local(start_at, "start_at")
    end = _aware_local(end_at, "end_at")
    if end <= start:
        raise DailyControlValidationError("end_at must be after start_at")
    return start, end


def _require_status(status: str, allowed: frozenset[str], field_name: str) -> None:
    if status not in allowed:
        raise DailyControlValidationError(
            f"{field_name} must be one of {sorted(allowed)}, got {status!r}"
        )


class DailyScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, user_id: int, usage_date: date, status: str = "draft"
    ) -> DailySchedule:
        _require_status(status, SCHEDULE_STATUSES, "schedule status")
        existing = await self.get(user_id=user_id, usage_date=usage_date)
        if existing is not None:
            return existing
        now = now_tz()
        schedule = DailySchedule(
            user_id=user_id,
            usage_date=usage_date,
            status=status,
            version=1,
            created_at=now,
            updated_at=now,
            confirmed_at=now if status == "confirmed" else None,
        )
        self.session.add(schedule)
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def get(self, *, user_id: int, usage_date: date) -> DailySchedule | None:
        result = await self.session.execute(
            select(DailySchedule).where(
                DailySchedule.user_id == user_id,
                DailySchedule.usage_date == usage_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, *, schedule_id: int, user_id: int) -> DailySchedule:
        result = await self.session.execute(
            select(DailySchedule).where(
                DailySchedule.id == schedule_id, DailySchedule.user_id == user_id
            )
        )
        schedule = result.scalar_one_or_none()
        if schedule is None:
            raise DailyControlNotFoundError(f"DailySchedule id={schedule_id} not found")
        return schedule

    async def update_status(
        self, *, schedule_id: int, user_id: int, status: str
    ) -> DailySchedule:
        _require_status(status, SCHEDULE_STATUSES, "schedule status")
        schedule = await self.get_by_id(schedule_id=schedule_id, user_id=user_id)
        schedule.status = status
        schedule.updated_at = now_tz()
        if status == "confirmed" and schedule.confirmed_at is None:
            schedule.confirmed_at = schedule.updated_at
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule


class TimeBlockService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.schedules = DailyScheduleService(session)

    async def create(
        self,
        *,
        schedule_id: int,
        user_id: int,
        start_at: datetime,
        end_at: datetime,
        title: str,
        category: str,
        block_type: str,
        flexibility: str,
        source_type: str,
        source_id: int | None = None,
        status: str = "planned",
    ) -> TimeBlock:
        start, end = _valid_interval(start_at, end_at)
        _require_status(status, TIME_BLOCK_STATUSES, "time block status")
        schedule = await self.schedules.get_by_id(
            schedule_id=schedule_id, user_id=user_id
        )
        duplicate = await self._exact_duplicate(schedule_id, start, end, title)
        if duplicate is not None:
            return duplicate
        await self._ensure_no_overlap(schedule_id, start, end)
        now = now_tz()
        block = TimeBlock(
            schedule_id=schedule_id,
            user_id=user_id,
            start_at=start,
            end_at=end,
            title=title,
            category=category,
            block_type=block_type,
            flexibility=flexibility,
            source_type=source_type,
            source_id=source_id,
            status=status,
            created_at=now,
            updated_at=now,
        )
        self.session.add(block)
        self._bump_confirmed(schedule, now)
        await self.session.commit()
        await self.session.refresh(block)
        return block

    async def list(self, *, schedule_id: int, user_id: int) -> list[TimeBlock]:
        await self.schedules.get_by_id(schedule_id=schedule_id, user_id=user_id)
        result = await self.session.execute(
            select(TimeBlock)
            .where(TimeBlock.schedule_id == schedule_id, TimeBlock.user_id == user_id)
            .order_by(TimeBlock.start_at, TimeBlock.id)
        )
        return list(result.scalars().all())

    async def update(
        self,
        *,
        block_id: int,
        user_id: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        title: str | None = None,
        category: str | None = None,
        status: str | None = None,
    ) -> TimeBlock:
        block = await self._get(block_id, user_id)
        new_start = start_at if start_at is not None else block.start_at.replace(tzinfo=APP_TZ)
        new_end = end_at if end_at is not None else block.end_at.replace(tzinfo=APP_TZ)
        start, end = _valid_interval(new_start, new_end)
        if status is not None:
            _require_status(status, TIME_BLOCK_STATUSES, "time block status")
        await self._ensure_no_overlap(block.schedule_id, start, end, ignore_id=block.id)
        schedule = await self.schedules.get_by_id(
            schedule_id=block.schedule_id, user_id=user_id
        )
        now = now_tz()
        block.start_at = start
        block.end_at = end
        if title is not None:
            block.title = title
        if category is not None:
            block.category = category
        if status is not None:
            block.status = status
        block.updated_at = now
        self._bump_confirmed(schedule, now)
        await self.session.commit()
        await self.session.refresh(block)
        return block

    async def delete(self, *, block_id: int, user_id: int) -> None:
        block = await self._get(block_id, user_id)
        schedule = await self.schedules.get_by_id(
            schedule_id=block.schedule_id, user_id=user_id
        )
        self._bump_confirmed(schedule, now_tz())
        await self.session.delete(block)
        await self.session.commit()

    async def _get(self, block_id: int, user_id: int) -> TimeBlock:
        result = await self.session.execute(
            select(TimeBlock).where(TimeBlock.id == block_id, TimeBlock.user_id == user_id)
        )
        block = result.scalar_one_or_none()
        if block is None:
            raise DailyControlNotFoundError(f"TimeBlock id={block_id} not found")
        return block

    async def _ensure_no_overlap(
        self,
        schedule_id: int,
        start: datetime,
        end: datetime,
        *,
        ignore_id: int | None = None,
    ) -> None:
        stmt = select(TimeBlock.id).where(
            TimeBlock.schedule_id == schedule_id,
            TimeBlock.status != "cancelled",
            TimeBlock.start_at < end,
            TimeBlock.end_at > start,
        )
        if ignore_id is not None:
            stmt = stmt.where(TimeBlock.id != ignore_id)
        if (await self.session.execute(stmt.limit(1))).scalar_one_or_none() is not None:
            raise DailyControlOverlapError("time block overlaps an existing block")

    async def _exact_duplicate(
        self, schedule_id: int, start: datetime, end: datetime, title: str
    ) -> TimeBlock | None:
        result = await self.session.execute(
            select(TimeBlock).where(
                TimeBlock.schedule_id == schedule_id,
                TimeBlock.start_at == start,
                TimeBlock.end_at == end,
                TimeBlock.title == title,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _bump_confirmed(schedule: DailySchedule, now: datetime) -> None:
        if schedule.status == "confirmed":
            schedule.version += 1
            schedule.updated_at = now


class ActivityEntryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        start_at: datetime,
        end_at: datetime,
        title: str,
        category: str,
        source: str,
        confidence: float | None = None,
        owner_confirmed: bool = False,
        waste_marked_by_owner: bool = False,
    ) -> ActivityEntry:
        start, end = _valid_interval(start_at, end_at)
        self._validate_owner_fields(confidence, owner_confirmed, waste_marked_by_owner)
        duplicate = await self._exact_duplicate(user_id, start, end, title)
        if duplicate is not None:
            return duplicate
        await self._ensure_no_overlap(user_id, start, end)
        now = now_tz()
        entry = ActivityEntry(
            user_id=user_id,
            usage_date=start.date(),
            start_at=start,
            end_at=end,
            title=title,
            category=category,
            source=source,
            confidence=confidence,
            owner_confirmed=owner_confirmed,
            waste_marked_by_owner=waste_marked_by_owner,
            created_at=now,
            updated_at=now,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def list_for_date(self, *, user_id: int, usage_date: date) -> list[ActivityEntry]:
        result = await self.session.execute(
            select(ActivityEntry)
            .where(
                ActivityEntry.user_id == user_id,
                ActivityEntry.usage_date == usage_date,
            )
            .order_by(ActivityEntry.start_at, ActivityEntry.id)
        )
        return list(result.scalars().all())

    async def update(
        self,
        *,
        entry_id: int,
        user_id: int,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        title: str | None = None,
        category: str | None = None,
        owner_confirmed: bool | None = None,
        waste_marked_by_owner: bool | None = None,
    ) -> ActivityEntry:
        entry = await self._get(entry_id, user_id)
        new_start = start_at if start_at is not None else entry.start_at.replace(tzinfo=APP_TZ)
        new_end = end_at if end_at is not None else entry.end_at.replace(tzinfo=APP_TZ)
        start, end = _valid_interval(new_start, new_end)
        confirmed = entry.owner_confirmed if owner_confirmed is None else owner_confirmed
        waste = (
            entry.waste_marked_by_owner
            if waste_marked_by_owner is None
            else waste_marked_by_owner
        )
        self._validate_owner_fields(entry.confidence, confirmed, waste)
        await self._ensure_no_overlap(user_id, start, end, ignore_id=entry.id)
        entry.start_at = start
        entry.end_at = end
        entry.usage_date = start.date()
        entry.owner_confirmed = confirmed
        entry.waste_marked_by_owner = waste
        if title is not None:
            entry.title = title
        if category is not None:
            entry.category = category
        entry.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def delete(self, *, entry_id: int, user_id: int) -> None:
        await self.session.execute(
            delete(ActivityEntry).where(
                ActivityEntry.id == entry_id, ActivityEntry.user_id == user_id
            )
        )
        await self.session.commit()

    async def _get(self, entry_id: int, user_id: int) -> ActivityEntry:
        result = await self.session.execute(
            select(ActivityEntry).where(
                ActivityEntry.id == entry_id, ActivityEntry.user_id == user_id
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            raise DailyControlNotFoundError(f"ActivityEntry id={entry_id} not found")
        return entry

    async def _ensure_no_overlap(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        *,
        ignore_id: int | None = None,
    ) -> None:
        stmt = select(ActivityEntry.id).where(
            ActivityEntry.user_id == user_id,
            ActivityEntry.start_at < end,
            ActivityEntry.end_at > start,
        )
        if ignore_id is not None:
            stmt = stmt.where(ActivityEntry.id != ignore_id)
        if (await self.session.execute(stmt.limit(1))).scalar_one_or_none() is not None:
            raise DailyControlOverlapError("activity overlaps an existing entry")

    async def _exact_duplicate(
        self, user_id: int, start: datetime, end: datetime, title: str
    ) -> ActivityEntry | None:
        result = await self.session.execute(
            select(ActivityEntry).where(
                ActivityEntry.user_id == user_id,
                ActivityEntry.start_at == start,
                ActivityEntry.end_at == end,
                ActivityEntry.title == title,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _validate_owner_fields(
        confidence: float | None, owner_confirmed: bool, waste_marked_by_owner: bool
    ) -> None:
        if confidence is not None and not 0 <= confidence <= 1:
            raise DailyControlValidationError("confidence must be between 0 and 1")
        if waste_marked_by_owner and not owner_confirmed:
            raise DailyControlValidationError(
                "waste may be marked only on an owner-confirmed entry"
            )


class CheckinService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        window_start: datetime,
        window_end: datetime,
        prompted_at: datetime,
        status: str = "pending",
    ) -> Checkin:
        start, end = _valid_interval(window_start, window_end)
        prompted = _aware_local(prompted_at, "prompted_at")
        _require_status(status, CHECKIN_STATUSES, "check-in status")
        existing = await self.get_for_window(
            user_id=user_id, window_start=start, window_end=end
        )
        if existing is not None:
            return existing
        now = now_tz()
        checkin = Checkin(
            user_id=user_id,
            window_start=start,
            window_end=end,
            prompted_at=prompted,
            answered_at=None,
            status=status,
            response_mode=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(checkin)
        await self.session.commit()
        await self.session.refresh(checkin)
        return checkin

    async def get_for_window(
        self, *, user_id: int, window_start: datetime, window_end: datetime
    ) -> Checkin | None:
        start, end = _valid_interval(window_start, window_end)
        result = await self.session.execute(
            select(Checkin).where(
                Checkin.user_id == user_id,
                Checkin.window_start == start,
                Checkin.window_end == end,
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        *,
        checkin_id: int,
        user_id: int,
        status: str,
        response_mode: str | None = None,
        answered_at: datetime | None = None,
    ) -> Checkin:
        _require_status(status, CHECKIN_STATUSES, "check-in status")
        result = await self.session.execute(
            select(Checkin).where(Checkin.id == checkin_id, Checkin.user_id == user_id)
        )
        checkin = result.scalar_one_or_none()
        if checkin is None:
            raise DailyControlNotFoundError(f"Checkin id={checkin_id} not found")
        checkin.status = status
        checkin.response_mode = response_mode
        checkin.answered_at = (
            _aware_local(answered_at, "answered_at")
            if answered_at is not None
            else checkin.answered_at
        )
        checkin.updated_at = now_tz()
        await self.session.commit()
        await self.session.refresh(checkin)
        return checkin
