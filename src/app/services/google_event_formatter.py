from __future__ import annotations

from collections.abc import Sequence

from app.core.time import APP_TZ


def format_google_event_line(event) -> str | None:
    if getattr(event, "status", None) == "cancelled":
        return None

    summary = getattr(event, "summary", "(no title)") or "(no title)"

    if getattr(event, "all_day", False):
        return f"• весь день — {summary}"

    start_at = getattr(event, "start_at", None)
    if start_at is None:
        return f"• {summary}"

    return f"• {start_at.astimezone(APP_TZ).strftime('%H:%M')} — {summary}"


def format_google_event_lines(
    events: Sequence,
    *,
    limit: int = 5,
) -> list[str]:
    lines: list[str] = []

    for event in events:
        line = format_google_event_line(event)
        if line is None:
            continue
        lines.append(line)
        if len(lines) >= limit:
            break

    remaining = len([event for event in events if format_google_event_line(event) is not None]) - len(lines)
    if remaining > 0:
        lines.append(f"• ещё: {remaining}")

    return lines
