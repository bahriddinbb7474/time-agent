from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_checkin_keyboard(checkin_id: int) -> InlineKeyboardMarkup:
    actions = (
        ("✅ Всё по плану", "aligned"),
        ("▶️ Начал", "started"),
        ("⏸ Отложить", "defer"),
        ("❓ Не помню", "unknown"),
        ("✏️ Другое", "other"),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f"checkin:{checkin_id}:{action}")]
            for text, action in actions
        ]
    )
