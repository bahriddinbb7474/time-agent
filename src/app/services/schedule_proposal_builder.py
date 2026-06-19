from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailySchedule, TimeBlock
from app.services.daily_control_service import (
    DailyControlValidationError,
    DailyScheduleService,
    TimeBlockService,
)


PROPOSAL_TYPE = "daily_schedule_draft"
SUPPORTED_BLOCK_TYPES = frozenset(
    {"sleep", "prayer", "fixed_task", "family", "target", "task", "buffer", "rest"}
)


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

    @property
    def version(self) -> int:
        return self.schedule.version


class ScheduleProposalBuilder:
    """Build and persist an owner-scoped draft without publishing it."""

    def __init__(self, session: AsyncSession) -> None:
        self.schedules = DailyScheduleService(session)
        self.blocks = TimeBlockService(session)

    async def build(
        self,
        *,
        usage_date: date,
        user_id: int,
        timezone: str,
        block_inputs: list[ProposalBlockInput] | tuple[ProposalBlockInput, ...] = (),
    ) -> ScheduleProposal:
        tz = self._timezone(timezone)
        schedule = await self.schedules.create(
            user_id=user_id, usage_date=usage_date, status="draft"
        )
        if schedule.status != "draft":
            raise DailyControlValidationError(
                "schedule proposal requires an existing or new draft schedule"
            )

        for item in sorted(block_inputs, key=self._sort_key):
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
        )

    @staticmethod
    def _timezone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError as exc:
            raise DailyControlValidationError(f"unknown timezone: {name}") from exc

    @staticmethod
    def _sort_key(item: ProposalBlockInput) -> tuple[datetime, datetime, str, str]:
        return item.start_at, item.end_at, item.block_type, item.title

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

