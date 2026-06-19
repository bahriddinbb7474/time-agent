import sqlite3
import tempfile
from pathlib import Path

from app.db.migration_runner import run_migrations


EXPECTED_TABLES = {
    "daily_schedules",
    "time_blocks",
    "activity_entries",
    "checkins",
}
MIGRATION_VERSION = "20260619_1200_add_daily_control_core"


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _indexes(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA index_list({table_name})")}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="time_agent_daily_control_migration_") as tmp:
        db_path = Path(tmp) / "daily_control.db"
        first = run_migrations(db_path)
        assert MIGRATION_VERSION in first.applied

        conn = sqlite3.connect(db_path)
        try:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            assert EXPECTED_TABLES.issubset(tables)
            assert {
                "id", "user_id", "usage_date", "status", "version",
                "created_at", "updated_at", "confirmed_at",
            }.issubset(_columns(conn, "daily_schedules"))
            assert {
                "id", "schedule_id", "user_id", "start_at", "end_at", "title",
                "category", "block_type", "flexibility", "source_type", "source_id",
                "status", "created_at", "updated_at",
            }.issubset(_columns(conn, "time_blocks"))
            assert {
                "id", "user_id", "usage_date", "start_at", "end_at", "title",
                "category", "source", "confidence", "owner_confirmed",
                "waste_marked_by_owner", "created_at", "updated_at",
            }.issubset(_columns(conn, "activity_entries"))
            assert {
                "id", "user_id", "window_start", "window_end", "prompted_at",
                "answered_at", "status", "response_mode", "created_at", "updated_at",
            }.issubset(_columns(conn, "checkins"))
            assert "ix_daily_schedules_user_date" in _indexes(conn, "daily_schedules")
            assert "ix_time_blocks_user_start" in _indexes(conn, "time_blocks")
            assert "ix_activity_entries_user_date" in _indexes(conn, "activity_entries")
            assert "ix_checkins_user_window" in _indexes(conn, "checkins")
            foreign_keys = conn.execute("PRAGMA foreign_key_list(time_blocks)").fetchall()
            assert any(row[2] == "daily_schedules" and row[6] == "CASCADE" for row in foreign_keys)
            migration_count = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
                (MIGRATION_VERSION,),
            ).fetchone()[0]
            assert migration_count == 1
        finally:
            conn.close()

        second = run_migrations(db_path)
        assert second.applied == []
        assert MIGRATION_VERSION in second.skipped

    print("PASS: Daily Control core migration is isolated and idempotent")


if __name__ == "__main__":
    main()
