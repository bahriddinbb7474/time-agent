# Time-Agent

Telegram-first goal-driven life dispatcher / external memory.

Time-Agent connects life goals to the daily plan, helps during the day, captures
urgent changes and facts, summarizes approximately where 24 valuable hours went,
and helps improve tomorrow.

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

- Stages through 20.6: CLOSED / production PASS.
- Stage 20.7-A unknown policy hardening: local PASS (`a9e703e`).
- Production HEAD (last deployed): `8973f80`.
- Current implementation target: Stage 20-FINAL.

## Current Route

1. Stage 20-FINAL — 24-hour mirror MVP.
2. Stage 21 — Goal Engine.
3. Stage 22 — Ideas + Relationships.
4. Stage 23 — Production finish + final acceptance.

## Core Decisions

- Daily Targets is part of the main product and does not depend on LLM.
- Daily Control is part of the main product after Stage 19.
- Ideas and relationships are part of the v1 path.
- Sleep is a protected metric.
- `Впустую` is accepted only from owner text/voice and only after proposal confirmation; it is not a primary button UX.
- Button check-ins are rules-first and do not call LLM.
- Free text or voice uses at most one LLM call.
- The owner chooses the executor before each stage: Codex or Claude Code.

Google Calendar and external calendar integrations are removed from current scope.
Only legacy tables/repositories remain for a later safe cleanup audit.

## Verification

Use the project helper described in `AGENTS.md`:

```bash
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 -m pytest <test_path>
```

See `TESTS_LOG.md` for historical verification notes.
