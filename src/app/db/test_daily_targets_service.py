"""
Stage 18.7.2 — DailyTargetsService tests.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_daily_targets_service.py

Safety: all tests use tempfile.TemporaryDirectory. Production DB is never opened.
"""
from __future__ import annotations

import asyncio
import os
import tempfile as _tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.db.models import Base
from app.services.daily_targets_service import (
    DailyTargetNotFoundError,
    DailyTargetValidationError,
    DailyTargetsService,
)


# ── DB helpers ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _session_ctx():
    """Yield a fresh async session backed by a temp SQLite DB, then dispose engine."""
    with _tempfile.TemporaryDirectory(prefix="ta_targets_") as tmp:
        db_path = Path(tmp) / "targets_test.db"
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


# ── Normalization (pure static, no DB) ────────────────────────────────────────


def test_normalize_liters() -> None:
    v, u = DailyTargetsService.normalize(3.0, "liters")
    assert v == 3000.0
    assert u == "ml"
    print("PASS: test_normalize_liters")


def test_normalize_hours() -> None:
    v, u = DailyTargetsService.normalize(2.5, "hours")
    assert v == 150.0
    assert u == "minutes"
    print("PASS: test_normalize_hours")


def test_normalize_ml_passthrough() -> None:
    v, u = DailyTargetsService.normalize(500.0, "ml")
    assert v == 500.0
    assert u == "ml"
    print("PASS: test_normalize_ml_passthrough")


def test_normalize_minutes_passthrough() -> None:
    v, u = DailyTargetsService.normalize(30.0, "minutes")
    assert v == 30.0
    assert u == "minutes"
    print("PASS: test_normalize_minutes_passthrough")


def test_normalize_count_passthrough() -> None:
    v, u = DailyTargetsService.normalize(5.0, "count")
    assert v == 5.0
    assert u == "count"
    print("PASS: test_normalize_count_passthrough")


def test_normalize_pages_passthrough() -> None:
    v, u = DailyTargetsService.normalize(20.0, "pages")
    assert v == 20.0
    assert u == "pages"
    print("PASS: test_normalize_pages_passthrough")


# ── Status (pure static, no DB) ────────────────────────────────────────────────


def test_status_minimum_in_progress() -> None:
    assert DailyTargetsService.compute_status("minimum", 0.0, 3000.0) == "in_progress"
    print("PASS: test_status_minimum_in_progress")


def test_status_minimum_partial() -> None:
    assert DailyTargetsService.compute_status("minimum", 1000.0, 3000.0) == "partial"
    print("PASS: test_status_minimum_partial")


def test_status_minimum_reached_exact() -> None:
    assert DailyTargetsService.compute_status("minimum", 3000.0, 3000.0) == "reached"
    print("PASS: test_status_minimum_reached_exact")


def test_status_minimum_exceeded_counts_as_reached() -> None:
    # minimum mode: exceeding target is still "reached", not penalised
    assert DailyTargetsService.compute_status("minimum", 4000.0, 3000.0) == "reached"
    print("PASS: test_status_minimum_exceeded_counts_as_reached")


def test_status_exact_in_progress() -> None:
    assert DailyTargetsService.compute_status("exact", 5.0, 20.0) == "in_progress"
    print("PASS: test_status_exact_in_progress")


def test_status_exact_reached() -> None:
    assert DailyTargetsService.compute_status("exact", 20.0, 20.0) == "reached"
    print("PASS: test_status_exact_reached")


def test_status_exact_exceeded() -> None:
    assert DailyTargetsService.compute_status("exact", 25.0, 20.0) == "exceeded"
    print("PASS: test_status_exact_exceeded")


def test_status_maximum_in_progress() -> None:
    assert DailyTargetsService.compute_status("maximum", 90.0, 120.0) == "in_progress"
    print("PASS: test_status_maximum_in_progress")


def test_status_maximum_at_limit() -> None:
    assert DailyTargetsService.compute_status("maximum", 120.0, 120.0) == "in_progress"
    print("PASS: test_status_maximum_at_limit")


def test_status_maximum_exceeded() -> None:
    assert DailyTargetsService.compute_status("maximum", 130.0, 120.0) == "exceeded"
    print("PASS: test_status_maximum_exceeded")


# ── Validation (pure static, no DB) ────────────────────────────────────────────


def test_validate_weekdays_mask_zero_raises() -> None:
    try:
        DailyTargetsService._validate_weekdays_mask(0)
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_weekdays_mask_zero_raises")


def test_validate_weekdays_mask_128_raises() -> None:
    try:
        DailyTargetsService._validate_weekdays_mask(128)
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_weekdays_mask_128_raises")


def test_validate_weekdays_mask_127_ok() -> None:
    DailyTargetsService._validate_weekdays_mask(127)
    DailyTargetsService._validate_weekdays_mask(1)
    print("PASS: test_validate_weekdays_mask_127_ok")


def test_validate_target_value_zero_raises() -> None:
    try:
        DailyTargetsService._validate_target_value(0.0)
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_target_value_zero_raises")


def test_validate_target_value_negative_raises() -> None:
    try:
        DailyTargetsService._validate_target_value(-1.0)
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_target_value_negative_raises")


def test_validate_target_mode_invalid_raises() -> None:
    try:
        DailyTargetsService._validate_target_mode("unknown")
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_target_mode_invalid_raises")


def test_validate_actual_value_negative_raises() -> None:
    try:
        DailyTargetsService._validate_actual_value(-0.1)
        raise AssertionError("expected DailyTargetValidationError")
    except DailyTargetValidationError:
        pass
    print("PASS: test_validate_actual_value_negative_raises")


def test_validate_actual_value_zero_ok() -> None:
    DailyTargetsService._validate_actual_value(0.0)
    print("PASS: test_validate_actual_value_zero_ok")


# ── DB-backed tests ────────────────────────────────────────────────────────────


def test_create_normalizes_liters_to_ml() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="liters", target_value=3.0
            )
            assert defn.unit == "ml"
            assert defn.target_value == 3000.0

    asyncio.run(_run())
    print("PASS: test_create_normalizes_liters_to_ml")


def test_create_normalizes_hours_to_minutes() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Sleep", unit="hours", target_value=7.5
            )
            assert defn.unit == "minutes"
            assert defn.target_value == 450.0

    asyncio.run(_run())
    print("PASS: test_create_normalizes_hours_to_minutes")


def test_create_pages_stored_as_is() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Quran", unit="pages", target_value=20.0
            )
            assert defn.unit == "pages"
            assert defn.target_value == 20.0

    asyncio.run(_run())
    print("PASS: test_create_pages_stored_as_is")


def test_create_invalid_mode_raises() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            try:
                await svc.create_target_definition(
                    title="Bad", unit="count", target_value=1.0,
                    target_mode="invalid",
                )
                raise AssertionError("expected DailyTargetValidationError")
            except DailyTargetValidationError:
                pass

    asyncio.run(_run())
    print("PASS: test_create_invalid_mode_raises")


def test_create_mask_zero_raises() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            try:
                await svc.create_target_definition(
                    title="Never", unit="count", target_value=1.0,
                    weekdays_mask=0,
                )
                raise AssertionError("expected DailyTargetValidationError")
            except DailyTargetValidationError:
                pass

    asyncio.run(_run())
    print("PASS: test_create_mask_zero_raises")


# ── Weekdays mask filtering ────────────────────────────────────────────────────


def test_weekdays_mask_monday_only_not_shown_tuesday() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            await svc.create_target_definition(
                title="Monday target", unit="count", target_value=1.0,
                weekdays_mask=1,  # Monday only
            )
            monday = date(2026, 6, 15)    # Monday weekday()=0
            tuesday = date(2026, 6, 16)   # Tuesday weekday()=1
            assert monday.weekday() == 0
            assert tuesday.weekday() == 1
            shown_mon = await svc.list_active_targets_for_date(monday)
            shown_tue = await svc.list_active_targets_for_date(tuesday)
            assert len(shown_mon) == 1
            assert len(shown_tue) == 0

    asyncio.run(_run())
    print("PASS: test_weekdays_mask_monday_only_not_shown_tuesday")


def test_weekdays_mask_all_days_shown_every_day() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            await svc.create_target_definition(
                title="Daily target", unit="count", target_value=1.0,
                weekdays_mask=127,
            )
            for day_offset in range(7):
                d = date(2026, 6, 16 + day_offset)
                shown = await svc.list_active_targets_for_date(d)
                assert len(shown) == 1, f"expected shown on {d}, weekday={d.weekday()}"

    asyncio.run(_run())
    print("PASS: test_weekdays_mask_all_days_shown_every_day")


def test_weekdays_mask_weekdays_only_not_weekend() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            # Mon=1, Tue=2, Wed=4, Thu=8, Fri=16 → sum=31
            await svc.create_target_definition(
                title="Weekday target", unit="count", target_value=1.0,
                weekdays_mask=31,
            )
            saturday = date(2026, 6, 20)   # weekday()=5
            sunday = date(2026, 6, 21)     # weekday()=6
            assert saturday.weekday() == 5
            assert sunday.weekday() == 6
            assert len(await svc.list_active_targets_for_date(saturday)) == 0
            assert len(await svc.list_active_targets_for_date(sunday)) == 0
            monday = date(2026, 6, 22)
            assert monday.weekday() == 0
            assert len(await svc.list_active_targets_for_date(monday)) == 1

    asyncio.run(_run())
    print("PASS: test_weekdays_mask_weekdays_only_not_weekend")


def test_inactive_target_not_shown() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            await svc.create_target_definition(
                title="Inactive", unit="count", target_value=1.0, active=False
            )
            shown = await svc.list_active_targets_for_date(date(2026, 6, 16))
            assert len(shown) == 0

    asyncio.run(_run())
    print("PASS: test_inactive_target_not_shown")


# ── Progress row lifecycle ─────────────────────────────────────────────────────


def test_progress_initial_state_is_no_data() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            progress = await svc.get_or_create_progress(defn.id, date(2026, 6, 16))
            assert progress.status == "no_data"
            assert progress.actual_value == 0.0
            assert progress.planned_value_snapshot == 3000.0

    asyncio.run(_run())
    print("PASS: test_progress_initial_state_is_no_data")


def test_progress_get_or_create_idempotent() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            p1 = await svc.get_or_create_progress(defn.id, d)
            p2 = await svc.get_or_create_progress(defn.id, d)
            assert p1.id == p2.id

    asyncio.run(_run())
    print("PASS: test_progress_get_or_create_idempotent")


def test_progress_unique_per_date() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            p1 = await svc.get_or_create_progress(defn.id, date(2026, 6, 16))
            p2 = await svc.get_or_create_progress(defn.id, date(2026, 6, 17))
            assert p1.id != p2.id
            assert p1.usage_date != p2.usage_date

    asyncio.run(_run())
    print("PASS: test_progress_unique_per_date")


def test_planned_snapshot_immutable_after_target_edit() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            progress = await svc.get_or_create_progress(defn.id, d)
            assert progress.planned_value_snapshot == 3000.0

            # Simulate owner changing the target value for tomorrow
            defn.target_value = 2000.0
            await session.commit()

            # The already-created progress row must still see the old snapshot
            await session.refresh(progress)
            assert progress.planned_value_snapshot == 3000.0

    asyncio.run(_run())
    print("PASS: test_planned_snapshot_immutable_after_target_edit")


def test_add_progress_accumulates() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            p = await svc.add_progress(defn.id, d, 500.0)
            assert p.actual_value == 500.0
            assert p.status == "partial"

            p = await svc.add_progress(defn.id, d, 700.0)
            assert p.actual_value == 1200.0
            assert p.status == "partial"

    asyncio.run(_run())
    print("PASS: test_add_progress_accumulates")


def test_add_progress_reaches_goal() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            d = date(2026, 6, 16)
            p = await svc.add_progress(defn.id, d, 3000.0)
            assert p.actual_value == 3000.0
            assert p.status == "reached"

    asyncio.run(_run())
    print("PASS: test_add_progress_reaches_goal")


def test_set_progress_absolute() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Sleep", unit="minutes", target_value=420.0
            )
            d = date(2026, 6, 16)
            p = await svc.set_progress(defn.id, d, 390.0, note="7h report")
            assert p.actual_value == 390.0
            assert p.status == "partial"
            assert p.note == "7h report"

            # Override with a higher value
            p = await svc.set_progress(defn.id, d, 450.0)
            assert p.actual_value == 450.0
            assert p.status == "reached"

    asyncio.run(_run())
    print("PASS: test_set_progress_absolute")


def test_add_negative_delta_raises() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            try:
                await svc.add_progress(defn.id, date(2026, 6, 16), -100.0)
                raise AssertionError("expected DailyTargetValidationError")
            except DailyTargetValidationError:
                pass

    asyncio.run(_run())
    print("PASS: test_add_negative_delta_raises")


def test_progress_not_found_raises() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            try:
                await svc.get_or_create_progress(9999, date(2026, 6, 16))
                raise AssertionError("expected DailyTargetNotFoundError")
            except DailyTargetNotFoundError:
                pass

    asyncio.run(_run())
    print("PASS: test_progress_not_found_raises")


# ── Mode-specific status via DB ────────────────────────────────────────────────


def test_exact_mode_exceeded() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Kaza", unit="count", target_value=5.0,
                target_mode="exact",
            )
            d = date(2026, 6, 16)
            p = await svc.set_progress(defn.id, d, 6.0)
            assert p.status == "exceeded"

    asyncio.run(_run())
    print("PASS: test_exact_mode_exceeded")


def test_maximum_mode_exceeded() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Screen", unit="minutes", target_value=120.0,
                target_mode="maximum",
            )
            d = date(2026, 6, 16)
            p = await svc.set_progress(defn.id, d, 130.0)
            assert p.status == "exceeded"

    asyncio.run(_run())
    print("PASS: test_maximum_mode_exceeded")


def test_maximum_mode_within_limit() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Screen", unit="minutes", target_value=120.0,
                target_mode="maximum",
            )
            d = date(2026, 6, 16)
            p = await svc.set_progress(defn.id, d, 90.0)
            assert p.status == "in_progress"

    asyncio.run(_run())
    print("PASS: test_maximum_mode_within_limit")


# ── Summary ────────────────────────────────────────────────────────────────────


def test_get_summary_for_date() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            d = date(2026, 6, 16)  # Tuesday, weekday()=1
            await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            await svc.create_target_definition(
                title="Mon only", unit="count", target_value=1.0,
                weekdays_mask=1,  # Monday only — must not appear on Tuesday
            )
            summary = await svc.get_summary_for_date(d)
            assert len(summary) == 1
            assert summary[0].definition.title == "Water"
            assert summary[0].progress is None  # not yet recorded

    asyncio.run(_run())
    print("PASS: test_get_summary_for_date")


def test_get_summary_shows_progress_when_set() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            d = date(2026, 6, 16)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            await svc.add_progress(defn.id, d, 1500.0)
            summary = await svc.get_summary_for_date(d)
            assert len(summary) == 1
            assert summary[0].progress is not None
            assert summary[0].progress.actual_value == 1500.0

    asyncio.run(_run())
    print("PASS: test_get_summary_shows_progress_when_set")


# ── Tashkent date boundary ─────────────────────────────────────────────────────


def test_explicit_usage_date_respected() -> None:
    """Progress rows for different dates (using explicit date args) stay separate."""
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            defn = await svc.create_target_definition(
                title="Water", unit="ml", target_value=3000.0
            )
            d1 = date(2026, 6, 16)
            d2 = date(2026, 6, 17)
            await svc.add_progress(defn.id, d1, 1000.0)
            await svc.add_progress(defn.id, d2, 500.0)

            p1 = await svc._fetch_progress(defn.id, d1)
            p2 = await svc._fetch_progress(defn.id, d2)
            assert p1 is not None and p1.actual_value == 1000.0
            assert p2 is not None and p2.actual_value == 500.0

    asyncio.run(_run())
    print("PASS: test_explicit_usage_date_respected")


# ── Runner ─────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_normalize_liters,
    test_normalize_hours,
    test_normalize_ml_passthrough,
    test_normalize_minutes_passthrough,
    test_normalize_count_passthrough,
    test_normalize_pages_passthrough,
    test_status_minimum_in_progress,
    test_status_minimum_partial,
    test_status_minimum_reached_exact,
    test_status_minimum_exceeded_counts_as_reached,
    test_status_exact_in_progress,
    test_status_exact_reached,
    test_status_exact_exceeded,
    test_status_maximum_in_progress,
    test_status_maximum_at_limit,
    test_status_maximum_exceeded,
    test_validate_weekdays_mask_zero_raises,
    test_validate_weekdays_mask_128_raises,
    test_validate_weekdays_mask_127_ok,
    test_validate_target_value_zero_raises,
    test_validate_target_value_negative_raises,
    test_validate_target_mode_invalid_raises,
    test_validate_actual_value_negative_raises,
    test_validate_actual_value_zero_ok,
    test_create_normalizes_liters_to_ml,
    test_create_normalizes_hours_to_minutes,
    test_create_pages_stored_as_is,
    test_create_invalid_mode_raises,
    test_create_mask_zero_raises,
    test_weekdays_mask_monday_only_not_shown_tuesday,
    test_weekdays_mask_all_days_shown_every_day,
    test_weekdays_mask_weekdays_only_not_weekend,
    test_inactive_target_not_shown,
    test_progress_initial_state_is_no_data,
    test_progress_get_or_create_idempotent,
    test_progress_unique_per_date,
    test_planned_snapshot_immutable_after_target_edit,
    test_add_progress_accumulates,
    test_add_progress_reaches_goal,
    test_set_progress_absolute,
    test_add_negative_delta_raises,
    test_progress_not_found_raises,
    test_exact_mode_exceeded,
    test_maximum_mode_exceeded,
    test_maximum_mode_within_limit,
    test_get_summary_for_date,
    test_get_summary_shows_progress_when_set,
    test_explicit_usage_date_respected,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    print(f"\nALL {len(SYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
