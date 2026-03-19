from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import APP_TZ, now_tz
from app.services.crisis_stack_service import CrisisStackService
from app.services.google_calendar_service import GoogleCalendarService
from app.services.task_sync_service import TaskSyncService
from app.services.task_sync_policy_service import KNOWN_CATEGORIES
from app.services.validation_result import ConflictType, ValidationSeverity

router = Router()
logger = logging.getLogger(__name__)

TIME_COLON_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2}):(?P<m>\d{2})(?!\d)")
TIME_SPACE_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2})\s+(?P<m>\d{2})(?!\d)")
TIME_DASH_RE = re.compile(r"(?<!\d)(?P<h>\d{1,2})-(?P<m>\d{2})(?!\d)")
TIME_COMPACT_RE = re.compile(r"(?<!\d)(?P<hhmm>\d{4})(?!\d)")
DUR_RE = re.compile(r"\b(?P<dur>\d{1,3})\b$")
REMINDER_LIKE_RE = re.compile("\u043d\u0430\u043f\u043e\u043c\u043d|remind|reminder|\U0001F514", flags=re.IGNORECASE)
PRAYER_NAMES = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

ADD_CONFIRM_PREFIX = "addconfirm"


@dataclass(slots=True)
class PendingAddRequest:
    category: str
    title: str
    planned_at: datetime | None
    duration_min: int
    suggested_slot_start: datetime | None
    allow_create_as_is: bool


PENDING_ADD_CONFIRMATIONS: dict[tuple[int, int], PendingAddRequest] = {}


def _extract_time_token(raw: str) -> tuple[int, int, str] | None:
    def _valid(h: int, m: int) -> bool:
        return 0 <= h <= 23 and 0 <= m <= 59

    m_colon = TIME_COLON_RE.search(raw)
    if m_colon:
        h = int(m_colon.group("h"))
        m = int(m_colon.group("m"))
        if _valid(h, m):
            return h, m, m_colon.group(0)

    m_space = TIME_SPACE_RE.search(raw)
    if m_space:
        h = int(m_space.group("h"))
        m = int(m_space.group("m"))
        if _valid(h, m):
            return h, m, m_space.group(0)

    m_dash = TIME_DASH_RE.search(raw)
    if m_dash:
        h = int(m_dash.group("h"))
        m = int(m_dash.group("m"))
        if _valid(h, m):
            return h, m, m_dash.group(0)

    m_compact = TIME_COMPACT_RE.search(raw)
    if m_compact:
        token = m_compact.group("hhmm")
        h = int(token[:2])
        m = int(token[2:])
        if _valid(h, m):
            return h, m, token

    return None


def _use_short_timed_default_duration(*, title: str) -> bool:
    if CrisisStackService.is_urgent_text(title):
        return True

    return REMINDER_LIKE_RE.search(title or "") is not None


def parse_add_payload(text: str) -> tuple[str, str, datetime | None, int]:
    raw = text.strip()

    category = "personal"
    parts = raw.split(maxsplit=1)
    if parts and parts[0].lower() in KNOWN_CATEGORIES:
        category = parts[0].lower()
        raw = parts[1].strip() if len(parts) > 1 else ""

    time_token = _extract_time_token(raw)
    planned_at = None

    if time_token:
        h, m, matched_token = time_token

        base = now_tz().date()
        raw_lower = raw.lower()

        if "Р·Р°РІС‚СЂР°" in raw_lower:
            base = base + timedelta(days=1)
            raw = re.sub(r"\bР·Р°РІС‚СЂР°\b", "", raw, flags=re.IGNORECASE)
        elif "СЃРµРіРѕРґРЅСЏ" in raw_lower:
            raw = re.sub(r"\bСЃРµРіРѕРґРЅСЏ\b", "", raw, flags=re.IGNORECASE)

        raw = re.sub(r"\s+", " ", raw.replace(matched_token, "", 1)).strip()

        planned_at = datetime(
            year=base.year,
            month=base.month,
            day=base.day,
            hour=h,
            minute=m,
            tzinfo=APP_TZ,
        )

    duration = 30
    m_d = DUR_RE.search(raw)
    if m_d:
        duration = int(m_d.group("dur"))
        raw = raw[: m_d.start()].strip()

    title = re.sub(r"\s+", " ", raw).strip()

    if not title:
        title = "\u0417\u0430\u0434\u0430\u0447\u0430"

    if planned_at is not None and m_d is None and _use_short_timed_default_duration(title=title):
        duration = 15

    return category, title, planned_at, duration


def _build_add_confirm_key(
    *,
    chat_id: int,
    user_id: int,
) -> tuple[int, int]:
    return chat_id, user_id


def _build_warning_keyboard(
    *,
    has_suggested_slot: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Оставить как есть",
                callback_data=f"{ADD_CONFIRM_PREFIX}:force",
            )
        ]
    ]

    if has_suggested_slot:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Перенести в окно",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:move",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"{ADD_CONFIRM_PREFIX}:cancel",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_hard_block_keyboard(
    *,
    has_suggested_slot: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Создать всё равно",
                callback_data=f"{ADD_CONFIRM_PREFIX}:force",
            )
        ]
    ]

    if has_suggested_slot:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Перенести в окно",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:move",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"{ADD_CONFIRM_PREFIX}:cancel",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)



def _build_prayer_shift_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сдвинуть",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:move",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Оставить как есть",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:force",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:cancel",
                )
            ],
        ]
    )


def _build_dhuhr_dead_zone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сдвинуть",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:move",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"{ADD_CONFIRM_PREFIX}:cancel",
                )
            ],
        ]
    )


def _build_dhuhr_dead_zone_message(*, suggested_slot_start: datetime) -> str:
    slot_text = suggested_slot_start.strftime("%H:%M")
    return (
        "С 13:00 до 13:20 время Зухра.\n"
        f"Ближайшее время для задачи — {slot_text}."
    )



def _extract_prayer_name(message_text: str | None) -> str:
    if not message_text:
        return "Namaz"

    for prayer_name in PRAYER_NAMES:
        if prayer_name.lower() in message_text.lower():
            return prayer_name

    return "Namaz"

def _build_prayer_shift_message(*, prayer_name: str, suggested_slot_start: datetime) -> str:
    slot_text = suggested_slot_start.strftime("%H:%M")
    return (
        f"Внимание: на это время выпадает Намаз {prayer_name}.\n"
        f"Предлагаю сдвинуть задачу на {slot_text}. Согласны?"
    )

def _build_sync_service(
    *,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
    bot,
) -> TaskSyncService:
    async def bot_notify_fn(*_args, **_kwargs):
        return None

    gcal_service = GoogleCalendarService(
        session_factory=lambda: session,
        bot_notify_fn=bot_notify_fn,
    )

    return TaskSyncService(
        session=session,
        gcal_service=gcal_service,
        scheduler=scheduler,
        bot=bot,
    )


async def _finalize_confirmation_ui(callback: CallbackQuery) -> None:
    if callback.message is None:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.exception("Failed to finalize add confirmation UI.")

@router.message(Command("add"))
async def add_cmd(
    message: Message,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    payload = message.text.removeprefix("/add").strip()

    if not payload:
        await message.answer(
            "Формат: /add work Встреча завтра 14:00 40\n"
            "Категории: work, family, health, prayer, personal, other"
        )
        return

    category, title, planned_at, duration = parse_add_payload(payload)

    sync_service = _build_sync_service(
        session=session,
        scheduler=scheduler,
        bot=message.bot,
    )

    result = await sync_service.create_task_with_google_sync(
        title=title,
        planned_at=planned_at,
        duration_min=duration,
        category=category,
        user_id=message.from_user.id if message.from_user else None,
    )

    validation_result = result.validation_result
    if validation_result is None:
        await message.answer(result.user_message)
        return

    if validation_result.severity not in {
        ValidationSeverity.WARNING,
        ValidationSeverity.HARD_BLOCK,
    }:
        await message.answer(result.user_message)
        return

    if message.chat is None or message.from_user is None:
        await message.answer(result.user_message)
        return

    is_dhuhr_dead_zone_recommendation = (
        validation_result.conflict_type == ConflictType.PRAYER
        and validation_result.recommended_action == "dhuhr_dead_zone_shift"
        and validation_result.suggested_slot_start is not None
    )

    is_prayer_shift_recommendation = (
        validation_result.conflict_type == ConflictType.PRAYER
        and validation_result.recommended_action == "shift_after_prayer"
        and validation_result.suggested_slot_start is not None
    )

    key = _build_add_confirm_key(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )

    PENDING_ADD_CONFIRMATIONS[key] = PendingAddRequest(
        category=category,
        title=title,
        planned_at=planned_at,
        duration_min=duration,
        suggested_slot_start=validation_result.suggested_slot_start,
        allow_create_as_is=True,
    )

    if is_dhuhr_dead_zone_recommendation:
        dhuhr_message = _build_dhuhr_dead_zone_message(
            suggested_slot_start=validation_result.suggested_slot_start,
        )
        await message.answer(
            dhuhr_message,
            reply_markup=_build_dhuhr_dead_zone_keyboard(),
        )
        return

    if is_prayer_shift_recommendation:
        prayer_name = _extract_prayer_name(validation_result.message)
        prayer_message = _build_prayer_shift_message(
            prayer_name=prayer_name,
            suggested_slot_start=validation_result.suggested_slot_start,
        )
        await message.answer(
            prayer_message,
            reply_markup=_build_prayer_shift_keyboard(),
        )
        return

    has_suggested_slot = validation_result.suggested_slot_start is not None

    if validation_result.severity == ValidationSeverity.HARD_BLOCK:
        keyboard = _build_hard_block_keyboard(has_suggested_slot=has_suggested_slot)
    else:
        keyboard = _build_warning_keyboard(has_suggested_slot=has_suggested_slot)

    await message.answer(result.user_message, reply_markup=keyboard)


@router.callback_query(F.data == f"{ADD_CONFIRM_PREFIX}:cancel")
async def add_confirm_cancel(callback: CallbackQuery):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    key = _build_add_confirm_key(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    pending = PENDING_ADD_CONFIRMATIONS.pop(key, None)

    await _finalize_confirmation_ui(callback)

    if pending is None:
        await callback.answer(
            "Подтверждение уже обработано или истекло.", show_alert=True
        )
        return

    await callback.message.answer("❌ Создание задачи отменено.")
    await callback.answer()


@router.callback_query(F.data == f"{ADD_CONFIRM_PREFIX}:force")
async def add_confirm_force(
    callback: CallbackQuery,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    key = _build_add_confirm_key(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    pending = PENDING_ADD_CONFIRMATIONS.pop(key, None)

    if pending is None:
        await _finalize_confirmation_ui(callback)
        await callback.answer(
            "Подтверждение уже истекло или не найдено.", show_alert=True
        )
        return

    sync_service = _build_sync_service(
        session=session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    try:
        result = await sync_service.create_task_with_google_sync(
            title=pending.title,
            planned_at=pending.planned_at,
            duration_min=pending.duration_min,
            category=pending.category,
            skip_context_validation=pending.allow_create_as_is,
            user_id=callback.from_user.id if callback.from_user else None,
        )

        await _finalize_confirmation_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
    except Exception:
        logger.exception("add_confirm_force failed during sync path")
        await _finalize_confirmation_ui(callback)
        await callback.message.answer(
            "⚠️ Не удалось синхронизировать задачу с Google Calendar. Попробуйте позже."
        )
        await callback.answer("Ошибка синхронизации", show_alert=True)


@router.callback_query(F.data == f"{ADD_CONFIRM_PREFIX}:move")
async def add_confirm_move(
    callback: CallbackQuery,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    key = _build_add_confirm_key(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )
    pending = PENDING_ADD_CONFIRMATIONS.pop(key, None)

    if pending is None:
        await _finalize_confirmation_ui(callback)
        await callback.answer(
            "Подтверждение уже истекло или не найдено.", show_alert=True
        )
        return

    if pending.suggested_slot_start is None:
        await _finalize_confirmation_ui(callback)
        await callback.answer("Свободное окно недоступно.", show_alert=True)
        return

    sync_service = _build_sync_service(
        session=session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    try:
        result = await sync_service.create_task_with_google_sync(
            title=pending.title,
            planned_at=pending.suggested_slot_start,
            duration_min=pending.duration_min,
            category=pending.category,
            user_id=callback.from_user.id if callback.from_user else None,
        )

        await _finalize_confirmation_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
    except Exception:
        logger.exception("add_confirm_move failed during sync path")
        await _finalize_confirmation_ui(callback)
        await callback.message.answer(
            "⚠️ Не удалось синхронизировать задачу с Google Calendar. Попробуйте позже."
        )
        await callback.answer("Ошибка синхронизации", show_alert=True)

