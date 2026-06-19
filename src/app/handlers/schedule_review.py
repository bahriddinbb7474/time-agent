from __future__ import annotations

from datetime import timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.core.time import now_tz
from app.keyboards.schedule_review import build_schedule_review_keyboard
from app.services.schedule_proposal_builder import ScheduleProposalBuilder
from app.services.schedule_proposal_formatter import format_schedule_proposal


router = Router()


def _is_owner(event, settings) -> bool:
    owner_id = getattr(settings, "allowed_telegram_id", None)
    user_id = getattr(getattr(event, "from_user", None), "id", None)
    return owner_id is not None and user_id == owner_id


@router.message(Command("schedule_tomorrow"))
async def schedule_tomorrow_cmd(
    message: Message,
    session: AsyncSession,
    settings=None,
) -> None:
    settings = settings or load_config()
    if not _is_owner(message, settings):
        return
    proposal = await ScheduleProposalBuilder(session).build(
        usage_date=now_tz().date() + timedelta(days=1),
        user_id=settings.allowed_telegram_id,
        timezone=settings.tz,
    )
    await message.answer(
        format_schedule_proposal(proposal),
        reply_markup=build_schedule_review_keyboard(proposal.schedule),
    )

