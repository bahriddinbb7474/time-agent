from __future__ import annotations

from app.services.schedule_proposal_builder import ScheduleProposal


MAX_SUMMARY_LINES = 15
_VISIBLE_TYPES = frozenset({"fixed_task", "family", "target", "task"})


def format_schedule_proposal(proposal: ScheduleProposal) -> str:
    """Return a compact, deterministic summary for future morning UX."""

    sleep_count = sum(block.block_type == "sleep" for block in proposal.blocks)
    prayer_count = sum(block.block_type == "prayer" for block in proposal.blocks)
    lines = [
        f"План на {proposal.usage_date.isoformat()} — черновик v{proposal.version}",
        f"Защищено: сон {sleep_count}, намаз {prayer_count}",
    ]

    visible = [block for block in proposal.blocks if block.block_type in _VISIBLE_TYPES]
    footer: list[str] = []
    buffer_minutes = sum(
        int((block.end_at - block.start_at).total_seconds() // 60)
        for block in proposal.blocks
        if block.block_type == "buffer"
    )
    if buffer_minutes:
        footer.append(f"Буфер: {buffer_minutes} мин")
    if proposal.unscheduled_items:
        footer.append(f"Не запланировано: {len(proposal.unscheduled_items)}")
    elif not visible:
        footer.append("Задач с явным временем пока нет")

    detail_limit = max(0, MAX_SUMMARY_LINES - len(lines) - len(footer))
    shown_limit = detail_limit
    if len(visible) > detail_limit and detail_limit > 0:
        shown_limit -= 1
    for block in visible[:shown_limit]:
        start = block.start_at.strftime("%H:%M")
        end = block.end_at.strftime("%H:%M")
        lines.append(f"{start}–{end} · {_safe_title(block.title)}")

    hidden_count = max(0, len(visible) - shown_limit)
    if hidden_count:
        lines.append(f"Ещё блоков: {hidden_count}")
    lines.extend(footer)

    return "\n".join(lines[:MAX_SUMMARY_LINES])


def _safe_title(value: str, limit: int = 60) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
