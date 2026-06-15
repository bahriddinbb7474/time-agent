# Time-Agent

Telegram-first Personal Mental Load Dispatcher / external memory assistant.

Canonical project plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

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
- Production code HEAD at smoke: `fd23d87`.
- Repository HEAD before v8.1 docs update: `41fd89c`.
- Current next stage: Stage 18.6-C0.

## Current Route

- 18.6-C0: token fields.
- 18.6-C: `/usage`.
- 18.6-D: hard limits.
- PRE-18.7 / PRE-19: audits and fixes.
- 18.7: Daily Targets MVP.
- 19: LLM Capture Intelligence.
- 20: Daily Control 24/7.
- 21: Task Lifecycle.
- 22: Production hardening + main DoD.
- 23: Idea Vault.
- 24: Statistics & Forecasting.

## Core Decisions

- Daily Targets is part of the main product and does not depend on LLM.
- Daily Control is part of the main product after Stage 19.
- Stage 23-24 are post-final modules and do not move the main DoD.
- Sleep is a protected metric.
- Owner-only category `впустую` is selected only by the owner.
- Button check-ins are rules-first and do not call LLM.
- Free text or voice uses at most one LLM call.
- The owner chooses the executor before each stage: Codex or Claude Code.

## Verification

Use the project helper described in `AGENTS.md`:

```bash
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 -m pytest <test_path>
```

See `TESTS_LOG.md` for historical verification notes.
