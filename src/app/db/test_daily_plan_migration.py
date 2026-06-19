import tempfile
from pathlib import Path

from app.db.migration_runner import run_migrations


def main():
    with tempfile.TemporaryDirectory(prefix="time_agent_migration_test_") as tmp_dir:
        db_path = Path(tmp_dir) / "migration_test.db"
        result = run_migrations(db_path)
        assert result.applied == [
            "20260101_0000_baseline_pre_stage14",
            "20260609_1300_add_daily_plan_lifecycle",
            "20260612_0300_add_capture_drafts",
            "20260614_2000_add_api_usage",
            "20260615_1000_add_token_usage",
            "20260616_0000_add_daily_targets",
            "20260617_1200_capture_drafts_add_advisor_proposal",
            "20260619_1200_add_daily_control_core",
        ]

        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
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

    print("PASS: DailyPlan migration smoke uses runner and isolated temp SQLite DB")


if __name__ == "__main__":
    main()
