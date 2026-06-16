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

- 18.6-C0 / 18.6-C / 18.6-D: CLOSED / PRODUCTION PASS.
- PRE-18.7-A/B: CLOSED / audit and crisis fix done.
- PRE-18.7-C: current — docs cleanup.
- Production HEAD (last deployed): `2c9b47e`.
- Repository HEAD: `1e81d73`.

## Current Route

- 18.6-C0: DONE.
- 18.6-C: DONE.
- 18.6-D: DONE.
- PRE-18.7: audits and fixes (in progress).
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
