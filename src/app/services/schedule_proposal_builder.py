from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailySchedule, TimeBlock
from app.services.daily_control_service import (
    DailyControlValidationError,
    DailyScheduleService,
    TimeBlockService,
)
from app.services.schedule_input_collector import ScheduleInputCollector


PROPOSAL_TYPE = "daily_schedule_draft"
SUPPORTED_BLOCK_TYPES = frozenset(
    {"sleep", "prayer", "fixed_task", "family", "target", "task", "buffer", "rest"}
)
BLOCK_TYPE_PRIORITY = {
    "sleep": 0,
    "prayer": 1,
    "fixed_task": 2,
    "family": 3,
    "target": 4,
    "task": 5,
    "rest": 6,
    "buffer": 7,
}
PROTECTED_BLOCK_TYPES = frozenset({"sleep", "prayer"})


@dataclass(frozen=True, slots=True)
class ProposalBlockInput:
    start_at: datetime
    end_at: datetime
    title: str
    category: str
    block_type: str
    flexibility: str = "flexible"
    source_type: str = "proposal"
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class ScheduleProposal:
    proposal_type: str
    usage_date: date
    user_id: int
    timezone: str
    schedule: DailySchedule
    blocks: tuple[TimeBlock, ...]
    unscheduled_items: tuple["UnscheduledItem", ...]

    @property
    def version(self) -> int:
        return self.schedule.version


@dataclass(frozen=True, slots=True)
class UnscheduledItem:
    item: ProposalBlockInput | None
    reason: str
    title: str
    source_type: str
    source_id: int | None = None


class ScheduleProposalBuilder:
    """Build and persist an owner-scoped draft without publishing it."""

    def __init__(self, session: AsyncSession) -> None:
        self.schedules = DailyScheduleService(session)
        self.blocks = TimeBlockService(session)
        self.inputs = ScheduleInputCollector(session)

    async def build(
        self,
        *,
        usage_date: date,
        user_id: int,
        timezone: str,
        block_inputs: list[ProposalBlockInput] | tuple[ProposalBlockInput, ...] = (),
        buffer_ratio: float = 0.10,
        collect_project_inputs: bool = True,
    ) -> ScheduleProposal:
        tz = self._timezone(timezone)
        if not 0 <= buffer_ratio <= 0.15:
            raise DailyControlValidationError("buffer_ratio must be between 0 and 0.15")
        schedule = await self.schedules.create(
            user_id=user_id, usage_date=usage_date, status="draft"
        )
        if schedule.status != "draft":
            raise DailyControlValidationError(
                "schedule proposal requires an existing or new draft schedule"
            )

        combined_inputs = list(block_inputs)
        collection_issues: list[UnscheduledItem] = []
        if collect_project_inputs:
            collected = await self.inputs.collect(
                usage_date=usage_date, user_id=user_id, timezone=tz
            )
            combined_inputs.extend(
                ProposalBlockInput(
                    start_at=item.start_at,
                    end_at=item.end_at,
                    title=item.title,
                    category=item.category,
                    block_type=item.block_type,
                    flexibility=item.flexibility,
                    source_type=item.source_type,
                    source_id=item.source_id,
                )
                for item in collected.blocks
            )
            collection_issues.extend(
                UnscheduledItem(
                    item=None,
                    reason=issue.reason,
                    title=issue.title,
                    source_type=issue.source_type,
                    source_id=issue.source_id,
                )
                for issue in collected.issues
            )
        accepted, unscheduled = self._place_inputs(
            combined_inputs, usage_date=usage_date, timezone=tz
        )
        unscheduled = collection_issues + unscheduled
        buffer = self._build_buffer(
            accepted, usage_date=usage_date, timezone=tz, ratio=buffer_ratio
        )
        if buffer is not None:
            accepted.append(buffer)

        for item in sorted(accepted, key=self._chronological_key):
            self._validate_input(item, usage_date=usage_date, timezone=tz)
            await self.blocks.create(
                schedule_id=schedule.id,
                user_id=user_id,
                start_at=item.start_at,
                end_at=item.end_at,
                title=item.title,
                category=item.category,
                block_type=item.block_type,
                flexibility=item.flexibility,
                source_type=item.source_type,
                source_id=item.source_id,
            )

        stored = await self.blocks.list(schedule_id=schedule.id, user_id=user_id)
        return ScheduleProposal(
            proposal_type=PROPOSAL_TYPE,
            usage_date=usage_date,
            user_id=user_id,
            timezone=timezone,
            schedule=schedule,
            blocks=tuple(stored),
            unscheduled_items=tuple(unscheduled),
        )

    @staticmethod
    def _timezone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise DailyControlValidationError(f"unknown timezone: {name}") from exc

    @staticmethod
    def _sort_key(item: ProposalBlockInput) -> tuple[int, datetime, datetime, str]:
        return (
            BLOCK_TYPE_PRIORITY[item.block_type],
            item.start_at,
            item.end_at,
            item.title,
        )

    @staticmethod
    def _chronological_key(item: ProposalBlockInput) -> tuple[datetime, datetime, str]:
        return item.start_at, item.end_at, item.title

    def _place_inputs(
        self,
        block_inputs: list[ProposalBlockInput] | tuple[ProposalBlockInput, ...],
        *,
        usage_date: date,
        timezone: ZoneInfo,
    ) -> tuple[list[ProposalBlockInput], list[UnscheduledItem]]:
        for item in block_inputs:
            self._validate_input(item, usage_date=usage_date, timezone=timezone)
        accepted: list[ProposalBlockInput] = []
        unscheduled: list[UnscheduledItem] = []
        for item in sorted(block_inputs, key=self._sort_key):
            conflict = next(
                (
                    placed
                    for placed in accepted
                    if placed.start_at < item.end_at and placed.end_at > item.start_at
                ),
                None,
            )
            if conflict is None:
                accepted.append(item)
                continue
            if (
                item.block_type in PROTECTED_BLOCK_TYPES
                and conflict.block_type in PROTECTED_BLOCK_TYPES
            ):
                raise DailyControlValidationError(
                    "protected sleep/prayer proposal blocks must not overlap"
                )
            unscheduled.append(
                UnscheduledItem(
                    item=item,
                    reason=f"overlaps higher-priority {conflict.block_type} block",
                    title=item.title,
                    source_type=item.source_type,
                    source_id=item.source_id,
                )
            )
        return accepted, unscheduled

    @staticmethod
    def _build_buffer(
        accepted: list[ProposalBlockInput],
        *,
        usage_date: date,
        timezone: ZoneInfo,
        ratio: float,
    ) -> ProposalBlockInput | None:
        if ratio == 0 or not accepted:
            return None
        day_start = datetime.combine(usage_date, time.min, timezone)
        day_end = day_start + timedelta(days=1)
        occupied = sorted(accepted, key=ScheduleProposalBuilder._chronological_key)
        gaps: list[tuple[datetime, datetime]] = []
        cursor = day_start
        for item in occupied:
            start = max(item.start_at.astimezone(timezone), day_start)
            end = min(item.end_at.astimezone(timezone), day_end)
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < day_end:
            gaps.append((cursor, day_end))
        free_seconds = sum((end - start).total_seconds() for start, end in gaps)
        if free_seconds <= 0:
            return None
        duration = timedelta(seconds=max(15 * 60, int(free_seconds * ratio)))
        viable = [(start, end) for start, end in gaps if end - start >= duration]
        if not viable:
            return None
        start, end = max(viable, key=lambda gap: (gap[1] - gap[0], -gap[0].timestamp()))
        return ProposalBlockInput(
            start_at=end - duration,
            end_at=end,
            title="Buffer",
            category="buffer",
            block_type="buffer",
            flexibility="flexible",
            source_type="proposal_policy",
        )

    @staticmethod
    def _validate_input(
        item: ProposalBlockInput, *, usage_date: date, timezone: ZoneInfo
    ) -> None:
        if item.block_type not in SUPPORTED_BLOCK_TYPES:
            raise DailyControlValidationError(
                f"unsupported proposal block type: {item.block_type!r}"
            )
        if item.start_at.tzinfo is None or item.end_at.tzinfo is None:
            raise DailyControlValidationError("proposal block datetimes must be timezone-aware")
        if item.start_at.astimezone(timezone).date() != usage_date:
            raise DailyControlValidationError(
                "proposal block must start on the proposal date in its timezone"
            )
