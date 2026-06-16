"""
Stage 22.1 — backup service tests.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_backup_service.py

Safety: all tests use tempfile.TemporaryDirectory. Production DB is never opened.
"""
from __future__ import annotations

import asyncio
import gzip
import os
import sqlite3
import tempfile
import time
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from app.services.backup_service import (
    apply_retention,
    create_backup,
    validate_backup_file,
    run_backup_job,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_test_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO schema_migrations VALUES ('20260101_0000_baseline')")
    conn.execute("INSERT INTO schema_migrations VALUES ('20260609_1300_add_stage14')")
    conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO tasks VALUES (1, 'Test task')")
    conn.commit()
    conn.close()


class _MockBot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_document(self, chat_id, document, caption=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "caption": caption, "document": document})


# ── create_backup ─────────────────────────────────────────────────────────────


def test_create_backup_returns_gz_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        result = create_backup(db_path=db_path, backup_dir=backup_dir)

        assert result.exists()
        assert result.suffix == ".gz"
        assert result.stat().st_size > 0
    print("PASS: test_create_backup_returns_gz_file")


def test_create_backup_dir_created_if_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "deep" / "nested" / "backups"
        _make_test_db(db_path)

        create_backup(db_path=db_path, backup_dir=backup_dir)

        assert backup_dir.exists()
    print("PASS: test_create_backup_dir_created_if_missing")


def test_create_backup_is_valid_sqlite_gz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)

        with gzip.open(gz_path, "rb") as f:
            header = f.read(16)
        assert header.startswith(b"SQLite format 3")
    print("PASS: test_create_backup_is_valid_sqlite_gz")


def test_create_backup_preserves_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)

        restore = tmp_path / "restored.db"
        with gzip.open(gz_path, "rb") as f_in:
            restore.write_bytes(f_in.read())

        conn = sqlite3.connect(str(restore))
        rows = conn.execute("SELECT title FROM tasks ORDER BY id").fetchall()
        conn.close()

        assert rows == [("Test task",)]
    print("PASS: test_create_backup_preserves_data")


def test_create_backup_integrity_ok() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)

        restore = tmp_path / "check.db"
        with gzip.open(gz_path, "rb") as f_in:
            restore.write_bytes(f_in.read())

        conn = sqlite3.connect(str(restore))
        row = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()

        assert row[0] == "ok"
    print("PASS: test_create_backup_integrity_ok")


def test_create_backup_temp_file_cleaned_up() -> None:
    import glob as _glob

    tmp_dir = tempfile.gettempdir()
    before = set(_glob.glob(os.path.join(tmp_dir, "tmp*.sqlite")))

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)
        create_backup(db_path=db_path, backup_dir=backup_dir)

    after = set(_glob.glob(os.path.join(tmp_dir, "tmp*.sqlite")))
    leaked = after - before
    assert not leaked, f"Temp sqlite files leaked: {leaked}"
    print("PASS: test_create_backup_temp_file_cleaned_up")


# ── apply_retention ───────────────────────────────────────────────────────────


def test_retention_deletes_old_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)

        old_file = backup_dir / "old.sqlite.gz"
        old_file.write_bytes(b"old")
        old_mtime = time.time() - 8 * 86400  # 8 days ago
        os.utime(old_file, (old_mtime, old_mtime))

        new_file = backup_dir / "new.sqlite.gz"
        new_file.write_bytes(b"new")

        deleted = apply_retention(backup_dir=backup_dir, retention_days=7)

        assert deleted == 1
        assert not old_file.exists()
        assert new_file.exists()
    print("PASS: test_retention_deletes_old_files")


def test_retention_keeps_recent_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        f = backup_dir / "recent.sqlite.gz"
        f.write_bytes(b"recent")

        deleted = apply_retention(backup_dir=backup_dir, retention_days=7)

        assert deleted == 0
        assert f.exists()
    print("PASS: test_retention_keeps_recent_files")


def test_retention_zero_keeps_all() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        old_file = backup_dir / "ancient.sqlite.gz"
        old_file.write_bytes(b"data")
        ancient = time.time() - 365 * 86400
        os.utime(old_file, (ancient, ancient))

        deleted = apply_retention(backup_dir=backup_dir, retention_days=0)

        assert deleted == 0
        assert old_file.exists()
    print("PASS: test_retention_zero_keeps_all")


def test_retention_only_targets_sqlite_gz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        sql_gz = backup_dir / "old.sqlite.gz"
        sql_gz.write_bytes(b"data")
        old_mtime = time.time() - 10 * 86400
        os.utime(sql_gz, (old_mtime, old_mtime))

        other = backup_dir / "notes.txt"
        other.write_bytes(b"notes")
        os.utime(other, (old_mtime, old_mtime))

        deleted = apply_retention(backup_dir=backup_dir, retention_days=7)

        assert deleted == 1
        assert not sql_gz.exists()
        assert other.exists()
    print("PASS: test_retention_only_targets_sqlite_gz")


# ── validate_backup_file ──────────────────────────────────────────────────────


def test_validate_ok_backup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)
        result = validate_backup_file(gz_path)

        assert result["ok"] is True
        assert result["error"] is None
        assert "schema_migrations" in result["tables"]
        assert result["version_count"] == 2
    print("PASS: test_validate_ok_backup")


def test_validate_missing_schema_migrations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "no_migrations.db"
        backup_dir = tmp_path / "backups"

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)
        result = validate_backup_file(gz_path)

        assert result["ok"] is False
        assert "schema_migrations" in (result["error"] or "")
    print("PASS: test_validate_missing_schema_migrations")


def test_validate_corrupt_gz() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        backup_dir = Path(tmp)
        bad_gz = backup_dir / "corrupt.sqlite.gz"
        bad_gz.write_bytes(b"this is not gzip data at all")

        result = validate_backup_file(bad_gz)

        assert result["ok"] is False
        assert result["error"] is not None
    print("PASS: test_validate_corrupt_gz")


# ── run_backup_job ────────────────────────────────────────────────────────────


async def _test_backup_job_async() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        bot = _MockBot()

        await run_backup_job(
            db_path=db_path,
            backup_dir=backup_dir,
            chat_id=99999,
            retention_days=7,
            bot=bot,
        )

        assert len(bot.sent) == 1
        assert bot.sent[0]["chat_id"] == 99999
        assert bot.sent[0]["caption"] is not None

        files = list(backup_dir.glob("*.sqlite.gz"))
        assert len(files) == 1


def test_backup_job_sends_and_creates_file() -> None:
    asyncio.run(_test_backup_job_async())
    print("PASS: test_backup_job_sends_and_creates_file")


async def _test_backup_job_send_failure_does_not_abort_retention_async() -> None:
    import time as _time

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_path = tmp_path / "test.db"
        backup_dir = tmp_path / "backups"
        _make_test_db(db_path)

        old_file = backup_dir / "old.sqlite.gz"
        backup_dir.mkdir(parents=True, exist_ok=True)
        old_file.write_bytes(b"old backup data")
        old_mtime = _time.time() - 10 * 86400
        os.utime(old_file, (old_mtime, old_mtime))

        class _FailBot:
            async def send_document(self, *args, **kwargs):
                raise RuntimeError("Telegram send failed")

        await run_backup_job(
            db_path=db_path,
            backup_dir=backup_dir,
            chat_id=99999,
            retention_days=7,
            bot=_FailBot(),
        )

        assert not old_file.exists()


def test_backup_job_send_failure_still_runs_retention() -> None:
    asyncio.run(_test_backup_job_send_failure_does_not_abort_retention_async())
    print("PASS: test_backup_job_send_failure_still_runs_retention")


# ── runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_create_backup_returns_gz_file,
    test_create_backup_dir_created_if_missing,
    test_create_backup_is_valid_sqlite_gz,
    test_create_backup_preserves_data,
    test_create_backup_integrity_ok,
    test_create_backup_temp_file_cleaned_up,
    test_retention_deletes_old_files,
    test_retention_keeps_recent_files,
    test_retention_zero_keeps_all,
    test_retention_only_targets_sqlite_gz,
    test_validate_ok_backup,
    test_validate_missing_schema_migrations,
    test_validate_corrupt_gz,
    test_backup_job_sends_and_creates_file,
    test_backup_job_send_failure_still_runs_retention,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    print(f"\nALL {len(SYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
