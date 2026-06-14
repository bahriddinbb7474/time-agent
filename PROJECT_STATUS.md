# Project Status

> Summary only.
> Canonical project plan: `docs/TZ_TIME_AGENT_FINAL_v7_1.md`

## Current Stage

- Stage 18.6-P: CLOSED / PRODUCTION PASS.
- Production HEAD: `fd23d87`.
- Documentation HEAD: `3e98bcb`.
- Next stage: Stage 18.6-C0.
- Then: Stage 18.6-C `/usage`, Stage 18.6-D hard limits, audits, Stage 19.

## Stable Baseline

- Owner-only Telegram bot.
- SQLite persistence with project migration runner.
- Prayer-aware scheduling for Asia/Tashkent, Hanafi `school=1`.
- Task, Later Inbox, boss, focus, crisis, done, daily plan, morning briefing, and evening planning flows.
- DB-backed capture drafts with owner confirmation before task creation.
- Voice/STT/AI provider foundation remains disabled by default unless a later approved stage enables real providers.
- Production DB migration steps must use explicit backup, verification, and owner approval.

## Planning Rule

Use this file only as a short status snapshot. For any new stage, read and follow:

`docs/TZ_TIME_AGENT_FINAL_v7_1.md`
