from __future__ import annotations

import re
from dataclasses import dataclass

# Maps user-typed unit words (lowercased) to the unit values known by
# DailyTargetsService.normalize() — "liters", "hours", or passthrough units.
_UNIT_WORDS: dict[str, str] = {
    # ml / water
    "мл": "ml",
    "ml": "ml",
    "миллилитр": "ml",
    "миллилитра": "ml",
    "миллилитров": "ml",
    # liters
    "л": "liters",
    "литр": "liters",
    "литра": "liters",
    "литров": "liters",
    "liters": "liters",
    "liter": "liters",
    # hours
    "час": "hours",
    "часа": "hours",
    "часов": "hours",
    "hours": "hours",
    "hour": "hours",
    # minutes
    "мин": "minutes",
    "минут": "minutes",
    "минуты": "minutes",
    "минута": "minutes",
    "min": "minutes",
    "minutes": "minutes",
    # pages / sheets
    "страниц": "pages",
    "страницы": "pages",
    "страница": "pages",
    "листов": "pages",
    "лист": "pages",
    "листа": "pages",
    "листы": "pages",
    "стр": "pages",
    "pages": "pages",
    "page": "pages",
    # count
    "раз": "count",
    "раза": "count",
    "count": "count",
}

# Fixed short aliases: alias → canonical DB title.
# Applied only when the canonical target exists in available_titles.
_SHORT_ALIASES: dict[str, str] = {
    "каза": "Каза-намаз",
}

# Matches the value portion after the title keyword.
# Groups: (plus_sign, digits, unit_word)
_VALUE_RE = re.compile(
    r"^(\+?)(\d+(?:[.,]\d+)?)\s*([а-яёА-ЯЁa-zA-Z]*)\s*$"
)


@dataclass(slots=True)
class ParsedTargetUpdate:
    title: str      # canonical title from DB (as stored)
    value: float    # parsed numeric value
    is_delta: bool  # True → add_progress, False → set_progress
    raw_unit: str   # user-provided unit word, lowercased (may be "")


def parse_target_update(
    text: str,
    available_titles: list[str],
) -> ParsedTargetUpdate | None:
    """
    Try to parse *text* as a target progress update command.

    Returns None when:
    - text is empty or starts with "/" (slash commands not swallowed)
    - no known target keyword is found at the start
    - the numeric value part is missing or malformed
    - value is negative

    Never calls an LLM.  No DB access — caller supplies available_titles.
    """
    text = text.strip()
    if not text or text.startswith("/"):
        return None

    # Build keyword → canonical title map; try user-DB titles first
    keywords: dict[str, str] = {}
    for title in available_titles:
        keywords[title.lower()] = title

    # Apply fixed short aliases only when the canonical target exists
    for alias, canonical in _SHORT_ALIASES.items():
        if canonical in available_titles:
            keywords.setdefault(alias, canonical)

    text_lower = text.lower()
    matched_title: str | None = None
    remainder: str = ""

    # Check longest keyword first to prefer "Коран с детьми" over "Коран"
    for kw in sorted(keywords, key=len, reverse=True):
        if text_lower.startswith(kw):
            rest = text[len(kw):]
            # Require a word boundary: space/tab or end of string
            if not rest or rest[0] in (" ", "\t"):
                matched_title = keywords[kw]
                remainder = rest.strip()
                break

    if matched_title is None:
        return None

    # Bare title with no value is not a valid update
    if not remainder:
        return None

    m = _VALUE_RE.match(remainder)
    if m is None:
        return None

    plus_sign = m.group(1)
    num_str = m.group(2).replace(",", ".")
    raw_unit = m.group(3).lower().strip()

    try:
        value = float(num_str)
    except ValueError:
        return None

    if value < 0:
        return None

    return ParsedTargetUpdate(
        title=matched_title,
        value=value,
        is_delta=(plus_sign == "+"),
        raw_unit=raw_unit,
    )


def resolve_unit(raw_unit: str, fallback_unit: str) -> str:
    """
    Map a user-typed unit word to the unit accepted by DailyTargetsService.normalize().
    Falls back to the target's stored (canonical) unit when word is empty or unknown.
    """
    if not raw_unit:
        return fallback_unit
    return _UNIT_WORDS.get(raw_unit, fallback_unit)
