from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import now_tz
from app.db.models import DailyTargetDefinition
from app.services.daily_targets_seed import DEFAULT_TARGETS, seed_default_targets
from app.services.daily_targets_service import DailyTargetsService
from app.services.targets_parser import parse_target_update, resolve_unit

log = logging.getLogger("time-agent.handlers.targets")
router = Router()

# Static prefix set built from default target titles + known short aliases.
# Used as a fast pre-filter before any DB query — no LLM, no session needed.
_CANDIDATE_PREFIXES: tuple[str, ...] = tuple(
    sorted(
        {spec["title"].lower() for spec in DEFAULT_TARGETS} | {"каза"},
        key=len,
        reverse=True,
    )
)

_STATUS_EMOJI: dict[str, str] = {
    "no_data": "⬜",
    "in_progress": "🔵",
    "partial": "🟡",
    "reached": "✅",
    "exceeded": "⚠️",
}

_STATUS_LABELS: dict[str, str] = {
    "no_data": "нет данных",
    "in_progress": "в процессе",
    "partial": "частично",
    "reached": "выполнено",
    "exceeded": "превышено",
}


def _looks_like_target(text: str | None) -> bool:
    """
    Return True if *text* starts with a known target keyword followed by a
    word boundary (space or end of string).

    This is a static check with no DB access.  It is used as an aiogram
    message filter so that non-target texts fall through to the capture handler.
    """
    if not text:
        return False
    t = text.strip().lower()
    for prefix in _CANDIDATE_PREFIXES:
        if t.startswith(prefix):
            rest = t[len(prefix):]
            if not rest or rest[0] in (" ", "\t"):
                return True
    return False


def _status_label(status: str) -> str:
    emoji = _STATUS_EMOJI.get(status, "")
    label = _STATUS_LABELS.get(status, status)
    return f"{emoji} {label}"


@router.message(Command("targets"))
async def targets_cmd(message: Message, session: AsyncSession) -> None:
    today: date = now_tz().date()
    service = DailyTargetsService(session)

    # Idempotent seed if no targets exist yet
    row = await session.execute(select(DailyTargetDefinition).limit(1))
    if row.scalar_one_or_none() is None:
        await seed_default_targets(session)

    summary = await service.get_summary_for_date(today)

    if not summary:
        await message.answer("Нет активных целей на сегодня.")
        return

    lines = [f"Цели на {today.strftime('%d.%m.%Y')}:"]
    for item in summary:
        defn = item.definition
        prog = item.progress
        actual = prog.actual_value if prog else 0.0
        status = prog.status if prog else "no_data"
        lines.append(
            f"• {defn.title}: {actual:g}/{defn.target_value:g} {defn.unit}"
            f" — {_status_label(status)}"
        )

    await message.answer("\n".join(lines))


@router.message(F.text & ~F.text.startswith("/") & F.text.func(_looks_like_target))
async def target_update_text(message: Message, session: AsyncSession) -> None:
    """
    Handle free-text target updates such as:
        Вода +500 мл
        Сон 7 часов
        Коран +5 страниц
        Английский 20 минут
        Каза +1
        Коран с детьми 15 минут

    Runs BEFORE the capture handler because targets_router is registered first
    in main.py.  Texts not matching a target keyword never reach this handler
    (filter prevents it), so they fall through to capture as usual.
    No LLM is called.  No owner confirmation required for a progress update.
    """
    if message.text is None:
        return

    service = DailyTargetsService(session)
    today: date = now_tz().date()
    active = await service.list_active_targets_for_date(today)

    if not active:
        # No active targets today (e.g. seed not yet run) — let it pass silently.
        return

    available_titles = [t.title for t in active]
    parsed = parse_target_update(message.text, available_titles)

    if parsed is None:
        # Static filter matched the prefix (e.g. bare "Коран") but full parse
        # failed (no numeric value).  Return without answering; the message is
        # consumed here and won't reach capture — acceptable for MVP.
        log.debug("Target prefix matched but full parse failed: %r", message.text)
        return

    target = next((t for t in active if t.title == parsed.title), None)
    if target is None:
        log.debug("Parsed title %r not found in active targets", parsed.title)
        return

    # Convert parsed value to canonical storage unit via DailyTargetsService.normalize
    input_unit = resolve_unit(parsed.raw_unit, fallback_unit=target.unit)
    canonical_value, _ = DailyTargetsService.normalize(parsed.value, input_unit)

    try:
        if parsed.is_delta:
            progress = await service.add_progress(target.id, today, canonical_value)
        else:
            progress = await service.set_progress(target.id, today, canonical_value)
    except Exception:
        log.exception("Failed to update target progress for %r", parsed.title)
        await message.answer("❌ Ошибка обновления цели.")
        return

    op_word = "+" if parsed.is_delta else "="
    lines = [
        f"✏️ {target.title}",
        f"{op_word}{canonical_value:g} {target.unit}",
        f"Факт: {progress.actual_value:g}/{progress.planned_value_snapshot:g} {target.unit}",
        f"Статус: {_status_label(progress.status)}",
    ]
    await message.answer("\n".join(lines))
