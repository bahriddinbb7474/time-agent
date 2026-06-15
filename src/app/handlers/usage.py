from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.services.api_usage_service import ApiUsageService, DailyUsageSummary

router = Router()
log = logging.getLogger("time-agent.handlers.usage")


def _format_usage_message(summary: DailyUsageSummary) -> str:
    date_str = summary.usage_date.strftime("%d.%m.%Y")
    lines: list[str] = [f"📊 API usage — {date_str}", ""]

    if summary.total_rows == 0:
        lines.append("Сегодня API ещё не использовался.")
        lines.append("Стоимость: $0.000000")
        return "\n".join(lines)

    audio_str = f"{summary.stt_audio_seconds:.1f}".replace(".", ",")

    lines += [
        f"Запросы: {summary.request_count}",
        f"✅ Успешно: {summary.success_count}",
        f"❌ Ошибки: {summary.error_count}",
        f"⚪ Блокировок: {summary.limit_exceeded_count}",
        "",
        "🎙 STT",
        f"Запросы: {summary.stt_request_count}",
        f"Аудио: {audio_str} сек",
        "",
        "🧠 LLM",
        f"Запросы: {summary.llm_request_count}",
        f"Input tokens: {summary.llm_input_tokens}",
        f"Output tokens: {summary.llm_output_tokens}",
        "",
        f"💰 Стоимость: ${summary.estimated_cost_usd:.6f}",
    ]
    return "\n".join(lines)


@router.message(Command("usage"))
async def usage_cmd(message: Message, session: AsyncSession) -> None:
    today = now_tz().date()
    try:
        summary = await ApiUsageService(session).get_daily_summary(today)
    except Exception:
        log.exception("Failed to get daily usage summary")
        await message.answer("Не удалось получить данные об использовании API.")
        return

    await message.answer(_format_usage_message(summary))
