# Time-Agent

Telegram-first Personal Mental Load Dispatcher / external memory assistant.

Canonical project plan: `docs/TZ_TIME_AGENT_FINAL_v7_1.md`.

Current short snapshot: `TZ_CURRENT_SHORT.md`.

## Stack

- Python 3.11
- aiogram 3
- SQLAlchemy 2 async
- SQLite with aiosqlite
- APScheduler
- aiohttp
- Docker / Docker Compose

## Current Status

- Stage 18.6-P: CLOSED / PRODUCTION PASS.
- Production HEAD: `fd23d87`.
- Documentation HEAD: `3e98bcb`.
- Next: Stage 18.6-C0.
- Then: Stage 18.6-C `/usage`, Stage 18.6-D hard limits, audits, Stage 19.

## Core Capabilities

- Owner-only Telegram bot access.
- Local task, Later Inbox, boss, focus, crisis, and done flows.
- Prayer-aware scheduling for Asia/Tashkent with Hanafi `school=1`.
- Morning briefing and evening planning.
- DB-backed capture drafts with owner confirmation before task creation.
- Disabled-by-default STT and AI advisor provider foundation.
- SQLite migrations through the project migration runner.
- Safe debug/test behavior gated by config.

## Local Run

The Python entrypoint is:

```bash
python -m app.main
```

For local non-Docker execution, set `PYTHONPATH` so `app` resolves from `src`.

## Verification

Use the project helper described in `AGENTS.md`:

```bash
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 -m pytest <test_path>
```

See `TESTS_LOG.md` for historical verification notes.
