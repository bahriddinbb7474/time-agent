# Handoff Summary

## Project

Time-Agent is a Telegram-first personal time and task assistant. It manages local tasks, protected time windows, prayer-aware scheduling, Google Calendar integration, Quran progress, basic Siyam/health context, family contact candidates, and persistent reminders.

## Current State

- Python 3.11 async bot using aiogram, SQLAlchemy async SQLite, APScheduler, aiohttp, and Google Calendar API libraries.
- Main entrypoint: `src/app/main.py`.
- Database is initialized on startup with `create_all()` and seed data.
- Dockerfile and docker-compose are present for long-running bot deployment.
- Stage 6 Stabilization Gate is complete.
- Stage 7 local done/button slice is complete.
- Stage 8 Capture Mode + Later Inbox is complete.

## What Works in Code

- Owner-only Telegram access.
- `/start`, `/rules`, `/today`, `/add`, `/edit`, `/delete`, `/done`, `/later`, `/backlog`, `/boss`.
- Minimal `✅ Сделал` button from `/today` marks tasks done through `task_done:<id>`.
- Later Inbox uses existing `tasks` rows with `status="later"` and is shown in evening summary.
- `/health` owner-only runtime status command.
- Google Calendar OAuth, read today, debug, pull/reconcile, create/update/delete for allowed task categories.
- Prayer times fetch/cache and prayer reminder alerts.
- Context validation for sleep, second sleep, prayer, protected slots, and Siyam heavy-load warnings.
- Morning briefing and evening summary jobs.
- Quran progress and follow-up reminders.
- Basic family contact candidate generation.
- Boss/critical persistent alert queue.

## Key Risks

- No full automated pytest/unittest suite found.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; earlier broad mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake markers are intentional.
- Migration foundation exists in `migrations/`, but no runner or schema-changing migrations exist yet.
- Google Calendar sync is partly write-capable, so production use depends on OAuth secrets, token storage, and policy correctness.
- Marking tasks done is local-only; Google Calendar lifecycle behavior for done/cancelled/later is not implemented.
- Later Inbox is local-only; no AI/STT/voice capture is implemented.
- Boss alert cleanup on task done is still a follow-up.
- Crisis mode references `Task.user_id`, but the current `Task` model has no `user_id` column, so that path is effectively skipped.

## Next Priority

Prayer Protected Scheduling hardening or Evening Planning Engine, while tracking remaining lifecycle work: promote Later items, later/postpone/cancel semantics, richer buttons, boss alert cleanup on done, and Google Calendar lifecycle policy.
