import shutil
import sqlite3
import tempfile
from pathlib import Path

from app.db.migration_runner import MigrationError, run_migrations


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"
BASELINE_PATH = REAL_MIGRATIONS_DIR / "20260101_0000_baseline_pre_stage14.sql"
STAGE14_PATH = REAL_MIGRATIONS_DIR / "20260609_1300_add_daily_plan_lifecycle.sql"
STAGE16_3_PATH = REAL_MIGRATIONS_DIR / "20260612_0300_add_capture_drafts.sql"


EXPECTED_TABLES = {
    "alert_queue",
    "capture_drafts",
    "crisis_stack_tasks",
    "crisis_stacks",
    "daily_health_contexts",
    "daily_plans",
    "oauth_states",
    "prayer_times",
    "quran_progress",
    "relatives_contact_rules",
    "rules",
    "schema_migrations",
    "task_external_links",
    "tasks",
    "user_routines",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")}


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _migration_versions(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _copy_real_migration(path: Path, target_dir: Path) -> None:
    shutil.copy2(path, target_dir / path.name)


def _assert_final_schema(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        assert EXPECTED_TABLES.issubset(_table_names(conn))
        assert "completed_at" in _columns(conn, "tasks")
        assert {"id", "plan_date", "text", "source", "created_at", "updated_at"}.issubset(
            _columns(conn, "daily_plans")
        )
        assert _migration_versions(conn) == [
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
            "20260612_0300_add_capture_drafts",
        ]
    finally:
        conn.close()


def test_idempotency() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_runner_") as tmp_dir:
        db_path = Path(tmp_dir) / "runner.db"

        first = run_migrations(db_path)
        assert first.applied == [
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
            "20260612_0300_add_capture_drafts",
        ]
        assert first.skipped == []
        _assert_final_schema(db_path)

        conn = sqlite3.connect(db_path)
        try:
            schema_before = conn.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
        finally:
            conn.close()

        second = run_migrations(db_path)
        assert second.applied == []
        assert second.skipped == [
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
            "20260612_0300_add_capture_drafts",
        ]

        conn = sqlite3.connect(db_path)
        try:
            schema_after = conn.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            assert schema_after == schema_before
            assert len(_migration_versions(conn)) == 3
        finally:
            conn.close()


def test_failure_rolls_back_partial_schema_change() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_fail_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        db_path = tmp_path / "runner_fail.db"

        _copy_real_migration(BASELINE_PATH, migrations_dir)
        broken = migrations_dir / "20260102_0000_broken.sql"
        broken.write_text(
            """
            CREATE TABLE should_rollback (
                id INTEGER PRIMARY KEY
            );
            SELECT * FROM missing_table_for_failure;
            """,
            encoding="utf-8",
        )

        try:
            run_migrations(db_path, migrations_dir=migrations_dir)
            raise AssertionError("broken migration should fail")
        except MigrationError as exc:
            assert "20260102_0000_broken.sql" in str(exc)

        conn = sqlite3.connect(db_path)
        try:
            assert "should_rollback" not in _table_names(conn)
            assert _migration_versions(conn) == [
                "20260101_0000_baseline_pre_stage14",
            ]
        finally:
            conn.close()


def test_stage14_applies_after_baseline_only() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_compat_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        db_path = tmp_path / "runner_compat.db"

        _copy_real_migration(BASELINE_PATH, migrations_dir)
        first = run_migrations(db_path, migrations_dir=migrations_dir)
        assert first.applied == ["20260101_0000_baseline_pre_stage14"]

        conn = sqlite3.connect(db_path)
        try:
            assert "completed_at" not in _columns(conn, "tasks")
            assert "daily_plans" not in _table_names(conn)
        finally:
            conn.close()

        _copy_real_migration(STAGE14_PATH, migrations_dir)
        second = run_migrations(db_path, migrations_dir=migrations_dir)
        assert second.applied == ["20260609_1300_add_daily_plan_lifecycle"]

        conn = sqlite3.connect(db_path)
        try:
            assert "completed_at" in _columns(conn, "tasks")
            assert "daily_plans" in _table_names(conn)
            assert "capture_drafts" not in _table_names(conn)
        finally:
            conn.close()


def test_stage16_3_applies_after_stage14() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_capture_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        db_path = tmp_path / "runner_capture.db"

        _copy_real_migration(BASELINE_PATH, migrations_dir)
        _copy_real_migration(STAGE14_PATH, migrations_dir)
        first = run_migrations(db_path, migrations_dir=migrations_dir)
        assert first.applied == [
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
        ]

        conn = sqlite3.connect(db_path)
        try:
            assert "capture_drafts" not in _table_names(conn)
        finally:
            conn.close()

        _copy_real_migration(STAGE16_3_PATH, migrations_dir)
        second = run_migrations(db_path, migrations_dir=migrations_dir)
        assert second.applied == ["20260612_0300_add_capture_drafts"]
        _assert_final_schema(db_path)


def main() -> None:
    test_idempotency()
    test_failure_rolls_back_partial_schema_change()
    test_stage14_applies_after_baseline_only()
    test_stage16_3_applies_after_stage14()
    print("PASS: migration runner applies baseline, stage14, and rollback safely")


if __name__ == "__main__":
    main()
