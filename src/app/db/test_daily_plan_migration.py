import sqlite3
import tempfile
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "versions"
    / "20260609_1300_add_daily_plan_lifecycle.sql"
)


def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "migration_test.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title VARCHAR(256) NOT NULL,
                    planned_at DATETIME NULL,
                    duration_min INTEGER NOT NULL DEFAULT 30,
                    status VARCHAR(16) NOT NULL DEFAULT 'todo',
                    category VARCHAR(32) NOT NULL DEFAULT 'personal',
                    context_status VARCHAR(32) NOT NULL DEFAULT 'normal',
                    created_at DATETIME NOT NULL
                );
                """
            )

            conn.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))

            task_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            plan_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(daily_plans)").fetchall()
            }
            migration_rows = conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                ("20260609_1300_add_daily_plan_lifecycle",),
            ).fetchall()

            assert "completed_at" in task_columns
            assert {
                "id",
                "plan_date",
                "text",
                "source",
                "created_at",
                "updated_at",
            }.issubset(plan_columns)
            assert len(migration_rows) == 1
        finally:
            conn.close()

    print("PASS: DailyPlan migration smoke uses isolated temp SQLite DB")


if __name__ == "__main__":
    main()
