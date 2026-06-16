"""
Restore validation utility for Time-Agent SQLite backups.

Usage (run from project root):
    python -m app.db.restore_check data/backups/app.db.20260616_020000.sqlite.gz

Safety invariants:
    - decompresses backup into a temporary directory only
    - never opens, reads, or writes production data/app.db
    - read-only: no schema changes, no migrations
"""
import gzip
import sqlite3
import sys
import tempfile
from pathlib import Path


def _validate(backup_path: Path) -> bool:
    if not backup_path.exists():
        print(f"ERROR: file not found: {backup_path}")
        return False

    print(f"Checking: {backup_path.name}")

    with tempfile.TemporaryDirectory(prefix="time_agent_restore_check_") as tmp_dir:
        tmp_db = Path(tmp_dir) / "check.db"

        try:
            with gzip.open(backup_path, "rb") as f_in:
                tmp_db.write_bytes(f_in.read())
        except Exception as exc:
            print(f"ERROR: decompress failed: {exc}")
            return False

        conn = sqlite3.connect(str(tmp_db))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row[0] != "ok":
                print(f"FAIL: integrity_check = {row[0]}")
                return False
            print("OK: integrity_check = ok")

            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

            if "schema_migrations" not in tables:
                print("FAIL: schema_migrations table missing")
                return False

            count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            if count == 0:
                print("FAIL: schema_migrations is empty")
                return False

            print(f"OK: schema_migrations = {count} version(s)")

            for (version,) in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ):
                print(f"  - {version}")

        finally:
            conn.close()

    print(f"\nPASS: {backup_path.name}")
    return True


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m app.db.restore_check <backup.sqlite.gz>")
        sys.exit(1)

    ok = _validate(Path(sys.argv[1]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
