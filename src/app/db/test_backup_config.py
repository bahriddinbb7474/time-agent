"""
Stage 22.1 — backup config defaults and parsing tests.
Run: powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_backup_config.py
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from app.config import load_config


# ── helpers ───────────────────────────────────────────────────────────────────


_BACKUP_KEYS = {
    "BACKUP_ENABLED",
    "BACKUP_TELEGRAM_CHAT_ID",
    "BACKUP_HOUR",
    "BACKUP_MINUTE",
    "BACKUP_RETENTION_DAYS",
    "BACKUP_DIR",
}


def _load(**overrides) -> object:
    saved: dict[str, str | None] = {}
    for k in _BACKUP_KEYS:
        saved[k] = os.environ.get(k)
        if k in overrides:
            os.environ[k] = overrides[k]
        elif k in os.environ:
            del os.environ[k]
    try:
        return load_config()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── default tests ─────────────────────────────────────────────────────────────


def test_backup_disabled_by_default() -> None:
    cfg = _load()
    assert cfg.backup_enabled is False
    print("PASS: test_backup_disabled_by_default")


def test_backup_chat_id_none_by_default() -> None:
    cfg = _load()
    assert cfg.backup_telegram_chat_id is None
    print("PASS: test_backup_chat_id_none_by_default")


def test_backup_hour_default_2() -> None:
    cfg = _load()
    assert cfg.backup_hour == 2
    print("PASS: test_backup_hour_default_2")


def test_backup_minute_default_30() -> None:
    cfg = _load()
    assert cfg.backup_minute == 30
    print("PASS: test_backup_minute_default_30")


def test_backup_retention_default_7() -> None:
    cfg = _load()
    assert cfg.backup_retention_days == 7
    print("PASS: test_backup_retention_default_7")


def test_backup_dir_default() -> None:
    cfg = _load()
    assert cfg.backup_dir == Path("data/backups")
    print("PASS: test_backup_dir_default")


# ── enabled variants ──────────────────────────────────────────────────────────


def test_backup_enabled_true() -> None:
    assert _load(BACKUP_ENABLED="true").backup_enabled is True
    print("PASS: test_backup_enabled_true")


def test_backup_enabled_1() -> None:
    assert _load(BACKUP_ENABLED="1").backup_enabled is True
    print("PASS: test_backup_enabled_1")


def test_backup_enabled_yes() -> None:
    assert _load(BACKUP_ENABLED="yes").backup_enabled is True
    print("PASS: test_backup_enabled_yes")


def test_backup_enabled_false() -> None:
    assert _load(BACKUP_ENABLED="false").backup_enabled is False
    print("PASS: test_backup_enabled_false")


def test_backup_enabled_0() -> None:
    assert _load(BACKUP_ENABLED="0").backup_enabled is False
    print("PASS: test_backup_enabled_0")


# ── parsing tests ─────────────────────────────────────────────────────────────


def test_backup_chat_id_parsed() -> None:
    cfg = _load(BACKUP_TELEGRAM_CHAT_ID="987654321")
    assert cfg.backup_telegram_chat_id == 987654321
    assert isinstance(cfg.backup_telegram_chat_id, int)
    print("PASS: test_backup_chat_id_parsed")


def test_backup_hour_minute_parsed() -> None:
    cfg = _load(BACKUP_HOUR="3", BACKUP_MINUTE="15")
    assert cfg.backup_hour == 3
    assert cfg.backup_minute == 15
    print("PASS: test_backup_hour_minute_parsed")


def test_backup_retention_parsed() -> None:
    cfg = _load(BACKUP_RETENTION_DAYS="14")
    assert cfg.backup_retention_days == 14
    print("PASS: test_backup_retention_parsed")


def test_backup_dir_parsed() -> None:
    cfg = _load(BACKUP_DIR="/custom/backup/path")
    assert cfg.backup_dir == Path("/custom/backup/path")
    print("PASS: test_backup_dir_parsed")


def test_backup_fields_are_correct_types() -> None:
    cfg = _load(
        BACKUP_ENABLED="true",
        BACKUP_TELEGRAM_CHAT_ID="111",
        BACKUP_HOUR="1",
        BACKUP_MINUTE="0",
        BACKUP_RETENTION_DAYS="30",
        BACKUP_DIR="data/backups",
    )
    assert isinstance(cfg.backup_enabled, bool)
    assert isinstance(cfg.backup_telegram_chat_id, int)
    assert isinstance(cfg.backup_hour, int)
    assert isinstance(cfg.backup_minute, int)
    assert isinstance(cfg.backup_retention_days, int)
    assert isinstance(cfg.backup_dir, Path)
    print("PASS: test_backup_fields_are_correct_types")


# ── runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_backup_disabled_by_default,
    test_backup_chat_id_none_by_default,
    test_backup_hour_default_2,
    test_backup_minute_default_30,
    test_backup_retention_default_7,
    test_backup_dir_default,
    test_backup_enabled_true,
    test_backup_enabled_1,
    test_backup_enabled_yes,
    test_backup_enabled_false,
    test_backup_enabled_0,
    test_backup_chat_id_parsed,
    test_backup_hour_minute_parsed,
    test_backup_retention_parsed,
    test_backup_dir_parsed,
    test_backup_fields_are_correct_types,
]


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    print(f"\nALL {len(SYNC_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
