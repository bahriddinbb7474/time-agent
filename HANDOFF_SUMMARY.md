# Handoff Summary

## Project

Time-Agent is a Telegram-first personal time and task assistant. It manages local tasks, protected time windows, prayer-aware scheduling, Google Calendar integration, Quran progress, basic Siyam/health context, family contact candidates, and persistent reminders.

## Current State

- Python 3.11 async bot using aiogram, SQLAlchemy async SQLite, APScheduler, aiohttp, and Google Calendar API libraries.
- Main entrypoint: `src/app/main.py`.
- Database is initialized on startup with `create_all()` and seed data.
- Dockerfile and docker-compose are present for long-running bot deployment.
- README was missing/empty before this documentation pass.

## What Works in Code

- Owner-only Telegram access.
- `/start`, `/rules`, `/today`, `/add`, `/edit`, `/delete`.
- Google Calendar OAuth, read today, debug, pull/reconcile, create/update/delete for allowed task categories.
- Prayer times fetch/cache and prayer reminder alerts.
- Context validation for sleep, second sleep, prayer, protected slots, and Siyam heavy-load warnings.
- Morning briefing and evening summary jobs.
- Quran progress and follow-up reminders.
- Basic family contact candidate generation.
- Boss/critical persistent alert queue.

## Key Risks

- No real automated test suite found; only a manual OAuth repo script exists under `src/app/db/test_oauth_state_repo.py`.
- `.env.example` is empty despite required env variables in code.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; earlier broad mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake markers are intentional.
- SQLite schema is managed by `create_all()` only; no migration system is visible.
- Google Calendar sync is partly write-capable, so production use depends on OAuth secrets, token storage, and policy correctness.
- Crisis mode references `Task.user_id`, but the current `Task` model has no `user_id` column, so that path is effectively skipped.

## Next Priority

Stabilization Gate: fix config/docs mismatch, add smoke tests for startup/imports, cover task lifecycle and context validation, and keep UTF-8 checks in place before expanding features.
