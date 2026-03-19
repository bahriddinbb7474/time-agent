from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.quran_service import (
    QuranConfirmationRequired,
    QuranParseError,
    QuranService,
)

router = Router()

_SURAH_TO_CODE = {
    "Фатиха": "fatiha",
    "Бакара": "bakara",
}

_CODE_TO_SURAH = {v: k for k, v in _SURAH_TO_CODE.items()}


def _build_backward_confirmation_keyboard(
    *,
    surah: str,
    ayah: int,
    page: int,
) -> InlineKeyboardMarkup:
    surah_code = _SURAH_TO_CODE.get(surah)
    if surah_code is None:
        raise ValueError(f"Unsupported surah for callback payload: {surah}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Исправить ввод",
                    callback_data="quran_backward:fix",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔁 Сохранить как повторение",
                    callback_data=f"quran_backward:repeat:{surah_code}:{ayah}:{page}",
                )
            ],
        ]
    )


def _restore_payload_from_callback(callback_data: str) -> str:
    parts = callback_data.split(":")
    if len(parts) != 5:
        raise ValueError("Invalid quran backward callback format")

    prefix, kind, surah_code, ayah_raw, page_raw = parts

    if prefix != "quran_backward" or kind != "repeat":
        raise ValueError("Unsupported quran backward callback action")

    surah = _CODE_TO_SURAH.get(surah_code)
    if surah is None:
        raise ValueError("Unknown surah code in callback")

    ayah = int(ayah_raw)
    page = int(page_raw)

    return f"{surah} {ayah} {page}"


@router.message(Command("quran"))
async def quran_cmd(message: Message, session: AsyncSession) -> None:
    """
    Save Quran progress.

    Format:
    /quran [Сура] [Аят] [Лист]

    Example:
    /quran Бакара 270 46
    """
    payload = message.text.removeprefix("/quran").strip()

    if not payload:
        await message.answer(
            "Формат: /quran [Сура] [Аят] [Лист]\n" "Пример: /quran Бакара 270 46"
        )
        return

    service = QuranService(session)

    try:
        surah, ayah, page = service.parse_input(payload)
        entry = await service.save_progress_from_text(payload)
        summary = await service.get_daily_summary()
    except QuranConfirmationRequired as e:
        surah, ayah, page = service.parse_input(payload)

        lines = [
            "⚠️ Введена страница раньше предыдущей.",
            f"Последняя точка: стр. {e.previous_page}",
            f"Новая точка: стр. {e.new_page}",
            "",
            "Это может быть:",
            "1. Ошибка ввода",
            "2. Повторение / чтение другой суры",
            "",
            "Выберите действие:",
        ]
        await message.answer(
            "\n".join(lines),
            reply_markup=_build_backward_confirmation_keyboard(
                surah=surah,
                ayah=ayah,
                page=page,
            ),
        )
        return
    except QuranParseError as e:
        await message.answer(f"❌ {e}")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка сохранения Quran progress:\n{e}")
        return

    lines = [
        "✅ Прогресс по Корану сохранён.",
        f"Сура: {entry.surah}",
        f"Аят: {entry.ayah}",
        f"Лист: {entry.page}",
        "",
        f"Сегодня новый прогресс: {summary.pages_read_today} стр.",
        f"Осталось до цели: {summary.remaining_goal} стр.",
    ]

    if summary.goal_reached:
        lines.append("Дневная цель выполнена ✅")

    await message.answer("\n".join(lines))


@router.callback_query(F.data == "quran_backward:fix")
async def quran_backward_fix_callback(callback: CallbackQuery) -> None:
    await callback.answer("Запись не сохранена.")
    if callback.message:
        await callback.message.edit_text(
            "✏️ Ввод отменён.\n"
            "Исправьте команду и отправьте заново:\n"
            "/quran [Сура] [Аят] [Лист]"
        )


@router.callback_query(F.data.startswith("quran_backward:repeat:"))
async def quran_backward_repeat_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    if callback.message is None:
        await callback.answer("Сообщение не найдено.", show_alert=True)
        return

    try:
        payload = _restore_payload_from_callback(callback.data)
    except Exception:
        await callback.answer("Некорректные данные подтверждения.", show_alert=True)
        return

    service = QuranService(session)

    try:
        entry = await service.save_progress_from_text(payload, allow_backward=True)
        summary = await service.get_daily_summary()
    except QuranParseError as e:
        await callback.answer("Ошибка разбора ввода.", show_alert=True)
        await callback.message.edit_text(f"❌ {e}")
        return
    except Exception as e:
        await callback.answer("Ошибка сохранения.", show_alert=True)
        await callback.message.edit_text(f"❌ Ошибка сохранения Quran progress:\n{e}")
        return

    lines = [
        "🔁 Повторное чтение сохранено.",
        f"Сура: {entry.surah}",
        f"Аят: {entry.ayah}",
        f"Лист: {entry.page}",
        "",
        "Эта запись сохранена как повторение и не увеличивает дневную цель.",
        "",
        f"Сегодня новый прогресс: {summary.pages_read_today} стр.",
        f"Осталось до цели: {summary.remaining_goal} стр.",
    ]

    if summary.goal_reached:
        lines.append("Дневная цель выполнена ✅")

    await callback.answer("Повторение сохранено.")
    await callback.message.edit_text("\n".join(lines))


@router.message(Command("quran_status"))
async def quran_status_cmd(message: Message, session: AsyncSession) -> None:
    """
    Show current Quran daily summary.
    """
    service = QuranService(session)

    try:
        summary = await service.get_daily_summary()
    except Exception as e:
        await message.answer(f"❌ Ошибка получения Quran summary:\n{e}")
        return

    await message.answer(service.build_deficit_message(summary))
