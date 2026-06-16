import gzip
import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("time-agent.backup")


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    """Online backup via sqlite3.Connection.backup() — safe while DB is live.

    Copies to a temp file, runs PRAGMA integrity_check, then gzip-compresses
    to backup_dir. Temp file is always removed. Does not touch the source DB.
    Returns the path to the created .sqlite.gz file.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    gz_path = backup_dir / f"app.db.{timestamp}.sqlite.gz"

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(tmp_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        chk = sqlite3.connect(str(tmp_path))
        try:
            row = chk.execute("PRAGMA integrity_check").fetchone()
            if row[0] != "ok":
                raise RuntimeError(f"Backup integrity_check failed: {row[0]!r}")
        finally:
            chk.close()

        with tmp_path.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            f_out.write(f_in.read())
    finally:
        tmp_path.unlink(missing_ok=True)

    log.info("Backup created: name=%s bytes=%d", gz_path.name, gz_path.stat().st_size)
    return gz_path


def apply_retention(backup_dir: Path, retention_days: int) -> int:
    """Delete .sqlite.gz backups older than retention_days. Returns count deleted.

    retention_days <= 0 means keep all (no deletion).
    """
    if retention_days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    deleted = 0

    for f in backup_dir.glob("*.sqlite.gz"):
        mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            try:
                f.unlink()
                deleted += 1
                log.info("Retention: removed %s", f.name)
            except Exception:
                log.exception("Retention: failed to remove %s", f.name)

    return deleted


def validate_backup_file(backup_path: Path) -> dict:
    """Decompress backup into a temp dir and run integrity checks.

    Returns dict: ok (bool), tables (set[str]), version_count (int), error (str|None).
    Never touches production DB.
    """
    with tempfile.TemporaryDirectory(prefix="time_agent_restore_check_") as tmp_dir:
        tmp_db = Path(tmp_dir) / "check.db"

        try:
            with gzip.open(backup_path, "rb") as f_in:
                tmp_db.write_bytes(f_in.read())
        except Exception as exc:
            return {"ok": False, "tables": set(), "version_count": 0, "error": f"decompress: {exc}"}

        conn = sqlite3.connect(str(tmp_db))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if row[0] != "ok":
                return {
                    "ok": False,
                    "tables": set(),
                    "version_count": 0,
                    "error": f"integrity_check: {row[0]}",
                }

            tables: set[str] = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }

            if "schema_migrations" not in tables:
                return {
                    "ok": False,
                    "tables": tables,
                    "version_count": 0,
                    "error": "schema_migrations missing",
                }

            version_count: int = conn.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
        finally:
            conn.close()

    return {"ok": True, "tables": tables, "version_count": version_count, "error": None}


async def run_backup_job(
    *,
    db_path: Path,
    backup_dir: Path,
    chat_id: int,
    retention_days: int,
    bot,
) -> None:
    """Nightly backup job: create → integrity → gzip → send to Telegram → retention.

    Each phase is isolated: a failure in send or retention does not abort the others.
    """
    from aiogram.types import FSInputFile

    try:
        gz_path = create_backup(db_path=db_path, backup_dir=backup_dir)
    except Exception:
        log.exception("Nightly backup: creation failed")
        return

    try:
        caption = f"Ночной бэкап {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        backup_file = FSInputFile(gz_path, filename=gz_path.name)
        await bot.send_document(chat_id, document=backup_file, caption=caption)
        log.info("Nightly backup: sent to Telegram")
    except Exception:
        log.exception("Nightly backup: send to Telegram failed")

    try:
        deleted = apply_retention(backup_dir=backup_dir, retention_days=retention_days)
        if deleted:
            log.info("Nightly backup: retention removed %d file(s)", deleted)
    except Exception:
        log.exception("Nightly backup: retention cleanup failed")
