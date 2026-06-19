from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.core.time import now_tz
from app.keyboards.schedule_review import (
    CALLBACK_PREFIX,
    build_confirmed_schedule_keyboard,
    build_schedule_edit_keyboard,
    build_schedule_review_keyboard,
)
from app.services.daily_control_service import (
    DailyControlNotFoundError,
    DailyControlValidationError,
    TimeBlockService,
)
from app.services.schedule_confirmation_service import (
    ScheduleConfirmationConflictError,
    ScheduleConfirmationService,
)
from app.services.schedule_proposal_builder import (
    PROPOSAL_TYPE,
    ScheduleProposal,
    ScheduleProposalBuilder,
)
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
    usage_date = now_tz().date() + timedelta(days=1)
    confirmed = await ScheduleConfirmationService(session).get_confirmed_for_date(
        user_id=settings.allowed_telegram_id,
        usage_date=usage_date,
    )
    if confirmed is not None:
        proposal = await _proposal_from_schedule(
            session, confirmed, settings.allowed_telegram_id, settings.tz
        )
        await message.answer(
            format_schedule_proposal(proposal),
            reply_markup=build_confirmed_schedule_keyboard(confirmed),
        )
        return
    try:
        proposal = await ScheduleProposalBuilder(session).build(
            usage_date=usage_date,
            user_id=settings.allowed_telegram_id,
            timezone=settings.tz,
        )
    except DailyControlValidationError:
        await message.answer(
            "Не удалось построить черновик из-за конфликта защищённых интервалов. "
            "Расписание не подтверждено. Попробуй пересобрать позже или "
            "скорректировать исходные данные."
        )
        return
    await message.answer(
        format_schedule_proposal(proposal),
        reply_markup=build_schedule_review_keyboard(proposal.schedule),
    )


def _parse_callback(data: str | None):
    parts = (data or "").split(":")
    if len(parts) != 5 or parts[0] != CALLBACK_PREFIX:
        raise ValueError("invalid schedule review callback")
    action, schedule_id, version, compact_date = parts[1:]
    if action not in {"confirm", "decline", "rebuild", "edit"}:
        raise ValueError("unknown schedule review action")
    from datetime import datetime

    return action, int(schedule_id), int(version), datetime.strptime(
        compact_date, "%Y%m%d"
    ).date()


async def _proposal_from_schedule(session, schedule, user_id: int, timezone: str):
    blocks = await TimeBlockService(session).list(
        schedule_id=schedule.id, user_id=user_id
    )
    return ScheduleProposal(
        proposal_type=PROPOSAL_TYPE,
        usage_date=schedule.usage_date,
        user_id=user_id,
        timezone=timezone,
        schedule=schedule,
        blocks=tuple(blocks),
        unscheduled_items=(),
    )


async def _edit_callback_message(callback: CallbackQuery, text: str, reply_markup=None):
    if callback.message is not None:
        await callback.message.edit_text(text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith(CALLBACK_PREFIX + ":"))
async def schedule_review_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    settings=None,
) -> None:
    settings = settings or load_config()
    if not _is_owner(callback, settings):
        return
    try:
        action, schedule_id, version, usage_date = _parse_callback(callback.data)
    except (TypeError, ValueError):
        await callback.answer("Некорректная или устаревшая кнопка.", show_alert=True)
        return
    service = ScheduleConfirmationService(session)
    try:
        if action == "edit":
            schedule = await service.get(
                schedule_id=schedule_id,
                user_id=settings.allowed_telegram_id,
                usage_date=usage_date,
                version=version,
            )
            await _edit_callback_message(
                callback,
                "Точечные правки будут подключены следующим шагом.\n"
                "Защищённые блоки сна и намаза не изменяются.\n"
                "Сейчас безопасно доступна только пересборка текущих входов.",
                build_schedule_edit_keyboard(schedule),
            )
            await callback.answer("Режим безопасного редактирования.")
            return
        if action == "confirm":
            schedule = await service.confirm(
                schedule_id=schedule_id,
                user_id=settings.allowed_telegram_id,
                usage_date=usage_date,
                version=version,
            )
            proposal = await _proposal_from_schedule(
                session, schedule, settings.allowed_telegram_id, settings.tz
            )
            await _edit_callback_message(callback, format_schedule_proposal(proposal))
            await callback.answer("Расписание подтверждено.")
            return
        if action == "decline":
            schedule = await service.decline(
                schedule_id=schedule_id,
                user_id=settings.allowed_telegram_id,
                usage_date=usage_date,
                version=version,
            )
            proposal = await _proposal_from_schedule(
                session, schedule, settings.allowed_telegram_id, settings.tz
            )
            await _edit_callback_message(callback, format_schedule_proposal(proposal))
            await callback.answer("Черновик отклонён.")
            return

        schedule = await service.rebuild(
            schedule_id=schedule_id,
            user_id=settings.allowed_telegram_id,
            usage_date=usage_date,
            version=version,
        )
        proposal = await ScheduleProposalBuilder(session).build(
            usage_date=usage_date,
            user_id=settings.allowed_telegram_id,
            timezone=settings.tz,
        )
        await _edit_callback_message(
            callback,
            format_schedule_proposal(proposal),
            build_schedule_review_keyboard(schedule),
        )
        await callback.answer("Черновик пересобран.")
    except DailyControlNotFoundError:
        await callback.answer("Черновик не найден или уже недоступен.", show_alert=True)
    except ScheduleConfirmationConflictError as exc:
        await callback.answer(str(exc), show_alert=True)
