"""
Stage 18.7.3 — daily_targets_seed tests.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_daily_targets_seed.py

Safety: all tests use tempfile.TemporaryDirectory. Production DB is never opened.
"""
from __future__ import annotations

import asyncio
import os
import tempfile as _tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.db.models import Base, DailyTargetDefinition
from app.services.daily_targets_seed import DEFAULT_TARGETS, seed_default_targets
from app.services.daily_targets_service import DailyTargetsService


# ── DB helper ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _session_ctx():
    """Yield a fresh async session backed by a temp SQLite DB, then dispose engine."""
    with _tempfile.TemporaryDirectory(prefix="ta_seed_") as tmp:
        db_path = Path(tmp) / "seed_test.db"
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


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_seed_creates_all_defaults() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            created = await seed_default_targets(session)
            assert len(created) == len(DEFAULT_TARGETS), (
                f"Expected {len(DEFAULT_TARGETS)} created, got {len(created)}: {created}"
            )
            result = await session.execute(select(DailyTargetDefinition))
            titles = {row.title for row in result.scalars().all()}
            for spec in DEFAULT_TARGETS:
                assert spec["title"] in titles, f"Missing default: {spec['title']!r}"

    asyncio.run(_run())
    print("PASS: test_seed_creates_all_defaults")


def test_seed_repeated_no_duplicates() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            first = await seed_default_targets(session)
            assert len(first) == len(DEFAULT_TARGETS)

            second = await seed_default_targets(session)
            assert second == [], (
                f"Expected empty list on second run, got: {second}"
            )

            result = await session.execute(select(DailyTargetDefinition))
            rows = list(result.scalars().all())
            assert len(rows) == len(DEFAULT_TARGETS), (
                f"Expected {len(DEFAULT_TARGETS)} rows after two seed runs, got {len(rows)}"
            )

    asyncio.run(_run())
    print("PASS: test_seed_repeated_no_duplicates")


def test_seed_does_not_overwrite_existing() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            svc = DailyTargetsService(session)
            # Pre-create "Вода" with user-edited values (different from defaults)
            existing = await svc.create_target_definition(
                title="Вода",
                unit="ml",
                target_value=1500.0,
                category="custom",
            )
            existing_id = existing.id

            created = await seed_default_targets(session)

            assert "Вода" not in created, (
                "seed_default_targets must skip existing 'Вода'"
            )
            # Remaining 5 defaults must be created
            assert len(created) == len(DEFAULT_TARGETS) - 1, (
                f"Expected {len(DEFAULT_TARGETS) - 1} new targets, got {len(created)}"
            )

            # Existing "Вода" row must be unchanged
            result = await session.execute(
                select(DailyTargetDefinition).where(
                    DailyTargetDefinition.title == "Вода"
                )
            )
            rows = list(result.scalars().all())
            assert len(rows) == 1, f"Expected exactly 1 'Вода', got {len(rows)}"
            assert rows[0].id == existing_id
            assert rows[0].target_value == 1500.0
            assert rows[0].category == "custom"

    asyncio.run(_run())
    print("PASS: test_seed_does_not_overwrite_existing")


def test_seed_units_normalized() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            await seed_default_targets(session)
            result = await session.execute(select(DailyTargetDefinition))
            rows = {row.title: row for row in result.scalars().all()}

            voda = rows["Вода"]
            assert voda.unit == "ml", f"Вода: expected unit 'ml', got {voda.unit!r}"
            assert voda.target_value == 3000.0, (
                f"Вода: expected 3000.0 ml, got {voda.target_value}"
            )

            son = rows["Сон"]
            assert son.unit == "minutes", (
                f"Сон: expected unit 'minutes', got {son.unit!r}"
            )
            assert son.target_value == 360.0, (
                f"Сон: expected 360.0 minutes, got {son.target_value}"
            )

    asyncio.run(_run())
    print("PASS: test_seed_units_normalized")


def test_seed_weekdays_mask_valid() -> None:
    async def _run() -> None:
        async with _session_ctx() as session:
            await seed_default_targets(session)
            result = await session.execute(select(DailyTargetDefinition))
            for row in result.scalars().all():
                assert 1 <= row.weekdays_mask <= 127, (
                    f"{row.title!r}: weekdays_mask={row.weekdays_mask} is outside 1..127"
                )

    asyncio.run(_run())
    print("PASS: test_seed_weekdays_mask_valid")


# ── Runner ─────────────────────────────────────────────────────────────────────

SYNC_TESTS = [
    test_seed_creates_all_defaults,
    test_seed_repeated_no_duplicates,
    test_seed_does_not_overwrite_existing,
    test_seed_units_normalized,
    test_seed_weekdays_mask_valid,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    print(f"\nALL {len(SYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
