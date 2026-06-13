from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


log = logging.getLogger("time-agent.migrations")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"


class MigrationError(RuntimeError):
    pass


@dataclass(slots=True)
class MigrationRunResult:
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def run_migrations(
    db_path: str | Path,
    *,
    migrations_dir: str | Path | None = None,
) -> MigrationRunResult:
    db_path = Path(db_path)
    migrations_path = Path(migrations_dir) if migrations_dir else DEFAULT_MIGRATIONS_DIR

    if not migrations_path.exists():
        raise MigrationError(f"Migrations directory not found: {migrations_path}")

    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema_migrations(conn)
        applied_versions = _load_applied_versions(conn)
        result = MigrationRunResult()

        for migration_path in _iter_migration_files(migrations_path):
            version = migration_path.stem
            if version in applied_versions:
                result.skipped.append(version)
                log.info("Migration skipped: %s", version)
                continue

            _apply_migration(conn, migration_path)
            result.applied.append(version)
            applied_versions.add(version)
            log.info("Migration applied: %s", version)

        return result
    finally:
        conn.close()


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_applied_versions(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def _iter_migration_files(migrations_path: Path) -> list[Path]:
    return sorted(
        path
        for path in migrations_path.glob("*.sql")
        if path.is_file()
    )


def _apply_migration(conn: sqlite3.Connection, migration_path: Path) -> None:
    version = migration_path.stem
    statements = _split_sql_statements(migration_path.read_text(encoding="utf-8"))

    try:
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) "
            "VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise MigrationError(
            f"Migration failed: {migration_path.name}: {exc}"
        ) from exc


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False

    idx = 0
    while idx < len(sql):
        char = sql[idx]
        next_char = sql[idx + 1] if idx + 1 < len(sql) else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            current.append(char)
            idx += 1
            continue

        if not in_single_quote and not in_double_quote and char == "-" and next_char == "-":
            in_line_comment = True
            current.append(char)
            current.append(next_char)
            idx += 2
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if char == ";" and not in_single_quote and not in_double_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            idx += 1
            continue

        current.append(char)
        idx += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)

    return statements
