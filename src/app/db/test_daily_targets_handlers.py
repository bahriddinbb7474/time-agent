"""
Stage 18.7.4 — targets parser, filter, and service integration tests.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_daily_targets_handlers.py

Safety: DB-backed tests use tempfile.TemporaryDirectory. Production DB not touched.
"""
from __future__ import annotations

import asyncio
import os
import tempfile as _tempfile
from contextlib import asynccontextmanager
from pathlib import Path

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base, DailyTargetDefinition
from app.handlers.targets import _looks_like_target
from app.services.daily_targets_seed import DEFAULT_TARGETS, seed_default_targets
from app.services.daily_targets_service import DailyTargetsService
from app.services.targets_parser import ParsedTargetUpdate, parse_target_update, resolve_unit


# ── DB helper ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _session_ctx():
    """Yield a fresh async session backed by a temp SQLite DB, then dispose engine."""
    with _tempfile.TemporaryDirectory(prefix="ta_handlers_") as tmp:
        db_path = Path(tmp) / "handlers_test.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path.as_posix()}", echo=False
        )
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            async with Session() as session:
                yield session
        finally:
            await engine.dispose()


# ── Parser: TZ examples ────────────────────────────────────────────────────────

_TITLES = ["Вода", "Сон", "Каза-намаз", "Коран", "Английский", "Коран с детьми"]


def test_parser_water_add_ml() -> None:
    r = parse_target_update("Вода +500 мл", _TITLES)
    assert r is not None
    assert r.title == "Вода"
    assert r.value == 500.0
    assert r.is_delta is True
    assert r.raw_unit == "мл"
    print("PASS: test_parser_water_add_ml")


def test_parser_sleep_set_hours() -> None:
    r = parse_target_update("Сон 7 часов", _TITLES)
    assert r is not None
    assert r.title == "Сон"
    assert r.value == 7.0
    assert r.is_delta is False
    assert r.raw_unit == "часов"
    print("PASS: test_parser_sleep_set_hours")


def test_parser_quran_add_pages() -> None:
    r = parse_target_update("Коран +5 страниц", _TITLES)
    assert r is not None
    assert r.title == "Коран"
    assert r.value == 5.0
    assert r.is_delta is True
    assert r.raw_unit == "страниц"
    print("PASS: test_parser_quran_add_pages")


def test_parser_english_set_minutes() -> None:
    r = parse_target_update("Английский 20 минут", _TITLES)
    assert r is not None
    assert r.title == "Английский"
    assert r.value == 20.0
    assert r.is_delta is False
    assert r.raw_unit == "минут"
    print("PASS: test_parser_english_set_minutes")


def test_parser_kaza_alias() -> None:
    r = parse_target_update("Каза +1", _TITLES)
    assert r is not None
    assert r.title == "Каза-намаз"
    assert r.value == 1.0
    assert r.is_delta is True
    assert r.raw_unit == ""
    print("PASS: test_parser_kaza_alias")


def test_parser_quran_kids() -> None:
    r = parse_target_update("Коран с детьми 15 минут", _TITLES)
    assert r is not None
    assert r.title == "Коран с детьми"
    assert r.value == 15.0
    assert r.is_delta is False
    print("PASS: test_parser_quran_kids")


def test_parser_water_liters_decimal_comma() -> None:
    r = parse_target_update("Вода 1,5 литра", _TITLES)
    assert r is not None
    assert r.title == "Вода"
    assert r.value == 1.5
    assert r.raw_unit == "литра"
    print("PASS: test_parser_water_liters_decimal_comma")


def test_parser_no_unit_is_ok() -> None:
    r = parse_target_update("Коран +5", _TITLES)
    assert r is not None
    assert r.title == "Коран"
    assert r.value == 5.0
    assert r.raw_unit == ""
    print("PASS: test_parser_no_unit_is_ok")


# ── Parser: non-matching cases (must return None) ──────────────────────────────


def test_parser_generic_text_returns_none() -> None:
    r = parse_target_update("Купить молоко", _TITLES)
    assert r is None, f"Expected None, got {r}"
    print("PASS: test_parser_generic_text_returns_none")


def test_parser_slash_command_returns_none() -> None:
    r = parse_target_update("/targets", _TITLES)
    assert r is None, "Slash commands must not be captured by target parser"
    r2 = parse_target_update("/start", _TITLES)
    assert r2 is None
    print("PASS: test_parser_slash_command_returns_none")


def test_parser_unknown_title_returns_none() -> None:
    r = parse_target_update("Спорт 30 минут", _TITLES)
    assert r is None, f"Expected None for unknown title, got {r}"
    print("PASS: test_parser_unknown_title_returns_none")


def test_parser_bare_title_returns_none() -> None:
    # "Вода" alone — no value — should not match
    r = parse_target_update("Вода", _TITLES)
    assert r is None, f"Expected None for bare title, got {r}"
    print("PASS: test_parser_bare_title_returns_none")


def test_parser_negative_value_returns_none() -> None:
    # Negative values must not be accepted
    r = parse_target_update("Вода -500 мл", _TITLES)
    assert r is None, f"Expected None for negative value, got {r}"
    print("PASS: test_parser_negative_value_returns_none")


def test_parser_quran_kids_preferred_over_quran() -> None:
    # "Коран с детьми" should win even though "Коран" is also in titles
    r = parse_target_update("Коран с детьми 30 минут", _TITLES)
    assert r is not None
    assert r.title == "Коран с детьми", (
        f"Expected 'Коран с детьми', got {r.title!r}"
    )
    print("PASS: test_parser_quran_kids_preferred_over_quran")


def test_parser_empty_titles_returns_none() -> None:
    r = parse_target_update("Вода +500 мл", [])
    assert r is None
    print("PASS: test_parser_empty_titles_returns_none")


# ── resolve_unit ───────────────────────────────────────────────────────────────


def test_resolve_unit_ml() -> None:
    assert resolve_unit("мл", "count") == "ml"
    print("PASS: test_resolve_unit_ml")


def test_resolve_unit_liters() -> None:
    assert resolve_unit("литра", "ml") == "liters"
    print("PASS: test_resolve_unit_liters")


def test_resolve_unit_empty_falls_back() -> None:
    assert resolve_unit("", "minutes") == "minutes"
    print("PASS: test_resolve_unit_empty_falls_back")


def test_resolve_unit_unknown_falls_back() -> None:
    assert resolve_unit("кг", "count") == "count"
    print("PASS: test_resolve_unit_unknown_falls_back")


# ── Static filter: _looks_like_target ─────────────────────────────────────────


def test_filter_matches_water() -> None:
    assert _looks_like_target("Вода +500 мл") is True
    print("PASS: test_filter_matches_water")


def test_filter_matches_kaza_alias() -> None:
    assert _looks_like_target("Каза +1") is True
    print("PASS: test_filter_matches_kaza_alias")


def test_filter_matches_quran_kids() -> None:
    assert _looks_like_target("Коран с детьми 30 минут") is True
    print("PASS: test_filter_matches_quran_kids")


def test_filter_rejects_generic_text() -> None:
    assert _looks_like_target("Купить молоко") is False
    assert _looks_like_target("Позвонить маме") is False
    print("PASS: test_filter_rejects_generic_text")


def test_filter_rejects_slash_commands() -> None:
    # Slash commands start with "/" — filter must not swallow them
    assert _looks_like_target("/targets") is False
    assert _looks_like_target("/start") is False
    print("PASS: test_filter_rejects_slash_commands")


def test_filter_rejects_none_and_empty() -> None:
    assert _looks_like_target(None) is False  # type: ignore[arg-type]
    assert _looks_like_target("") is False
    print("PASS: test_filter_rejects_none_and_empty")


def test_filter_requires_word_boundary() -> None:
    # "Водопровод" starts with "вода" but has no word boundary → must not match
    assert _looks_like_target("Водопровод 5") is False
    print("PASS: test_filter_requires_word_boundary")


# ── Service integration: parser → DB update ────────────────────────────────────


def test_integration_water_add_ml() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            from datetime import date

            defn = await svc.create_target_definition(
                title="Вода", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            parsed = parse_target_update("Вода +500 мл", ["Вода"])
            assert parsed is not None
            assert parsed.is_delta is True

            input_unit = resolve_unit(parsed.raw_unit, fallback_unit=defn.unit)
            canonical_value, _ = DailyTargetsService.normalize(parsed.value, input_unit)
            assert canonical_value == 500.0  # мл stays ml

            progress = await svc.add_progress(defn.id, d, canonical_value)
            assert progress.actual_value == 500.0
            assert progress.status == "partial"

    asyncio.run(_run())
    print("PASS: test_integration_water_add_ml")


def test_integration_liters_normalized() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            from datetime import date

            defn = await svc.create_target_definition(
                title="Вода", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            parsed = parse_target_update("Вода 1,5 литра", ["Вода"])
            assert parsed is not None

            input_unit = resolve_unit(parsed.raw_unit, fallback_unit=defn.unit)
            canonical_value, _ = DailyTargetsService.normalize(parsed.value, input_unit)
            assert canonical_value == 1500.0  # 1.5 liters → 1500 ml

            progress = await svc.set_progress(defn.id, d, canonical_value)
            assert progress.actual_value == 1500.0

    asyncio.run(_run())
    print("PASS: test_integration_liters_normalized")


def test_integration_sleep_hours_normalized() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            from datetime import date

            defn = await svc.create_target_definition(
                title="Сон", unit="minutes", target_value=360.0
            )
            d = date(2026, 6, 16)
            parsed = parse_target_update("Сон 7 часов", ["Сон"])
            assert parsed is not None

            input_unit = resolve_unit(parsed.raw_unit, fallback_unit=defn.unit)
            canonical_value, _ = DailyTargetsService.normalize(parsed.value, input_unit)
            assert canonical_value == 420.0  # 7 hours → 420 minutes

            progress = await svc.set_progress(defn.id, d, canonical_value)
            assert progress.actual_value == 420.0
            assert progress.status == "reached"  # 420 >= 360 → reached

    asyncio.run(_run())
    print("PASS: test_integration_sleep_hours_normalized")


def test_integration_kaza_alias_no_unit() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            from datetime import date

            defn = await svc.create_target_definition(
                title="Каза-намаз", unit="count", target_value=5.0
            )
            d = date(2026, 6, 16)
            parsed = parse_target_update("Каза +1", ["Каза-намаз"])
            assert parsed is not None
            assert parsed.title == "Каза-намаз"
            assert parsed.value == 1.0
            assert parsed.raw_unit == ""

            # No unit word → fallback to target's stored unit "count" (passthrough)
            input_unit = resolve_unit(parsed.raw_unit, fallback_unit=defn.unit)
            canonical_value, _ = DailyTargetsService.normalize(parsed.value, input_unit)
            assert canonical_value == 1.0

            progress = await svc.add_progress(defn.id, d, canonical_value)
            assert progress.actual_value == 1.0

    asyncio.run(_run())
    print("PASS: test_integration_kaza_alias_no_unit")


def test_integration_seed_on_empty_then_list() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            # DB starts empty
            row = await session.execute(select(DailyTargetDefinition).limit(1))
            assert row.scalar_one_or_none() is None

            created = await seed_default_targets(session)
            assert len(created) == len(DEFAULT_TARGETS)

            svc = DailyTargetsService(session)
            from app.core.time import now_tz
            active = await svc.list_active_targets_for_date(now_tz().date())
            assert len(active) == len(DEFAULT_TARGETS)

    asyncio.run(_run())
    print("PASS: test_integration_seed_on_empty_then_list")


def test_integration_repeated_add_accumulates() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            from datetime import date

            defn = await svc.create_target_definition(
                title="Коран", unit="pages", target_value=20.0
            )
            d = date(2026, 6, 16)

            p1 = await svc.add_progress(defn.id, d, 5.0)
            assert p1.actual_value == 5.0
            assert p1.status == "partial"

            p2 = await svc.add_progress(defn.id, d, 5.0)
            assert p2.actual_value == 10.0

            p3 = await svc.add_progress(defn.id, d, 10.0)
            assert p3.actual_value == 20.0
            assert p3.status == "reached"

    asyncio.run(_run())
    print("PASS: test_integration_repeated_add_accumulates")


# ── Runner ─────────────────────────────────────────────────────────────────────

SYNC_TESTS = [
    test_parser_water_add_ml,
    test_parser_sleep_set_hours,
    test_parser_quran_add_pages,
    test_parser_english_set_minutes,
    test_parser_kaza_alias,
    test_parser_quran_kids,
    test_parser_water_liters_decimal_comma,
    test_parser_no_unit_is_ok,
    test_parser_generic_text_returns_none,
    test_parser_slash_command_returns_none,
    test_parser_unknown_title_returns_none,
    test_parser_bare_title_returns_none,
    test_parser_negative_value_returns_none,
    test_parser_quran_kids_preferred_over_quran,
    test_parser_empty_titles_returns_none,
    test_resolve_unit_ml,
    test_resolve_unit_liters,
    test_resolve_unit_empty_falls_back,
    test_resolve_unit_unknown_falls_back,
    test_filter_matches_water,
    test_filter_matches_kaza_alias,
    test_filter_matches_quran_kids,
    test_filter_rejects_generic_text,
    test_filter_rejects_slash_commands,
    test_filter_rejects_none_and_empty,
    test_filter_requires_word_boundary,
    test_integration_water_add_ml,
    test_integration_liters_normalized,
    test_integration_sleep_hours_normalized,
    test_integration_kaza_alias_no_unit,
    test_integration_seed_on_empty_then_list,
    test_integration_repeated_add_accumulates,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    print(f"\nALL {len(SYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
