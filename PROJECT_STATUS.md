# Project Status

## Current Stage

Prototype / pre-production stabilization. The project has meaningful feature code, persistent storage, scheduler recovery, and Docker files, but lacks a visible automated test suite and has configuration/documentation gaps.

## Working Features Visible in Code

- Telegram bot startup and polling through aiogram.
- Owner-only access control using `ALLOWED_TELEGRAM_ID`.
- SQLite persistence through SQLAlchemy async.
- Default protected slots and routines seeding.
- Task creation, editing, deletion, and daily listing.
- Context validation for sleep, second sleep, prayer windows, protected slots, and Siyam heavy-load warnings.
- Google Calendar OAuth, event reads, pull/reconcile, and category-limited write sync.
- Persistent alert queue with recovery after restart.
- Morning briefing at 08:30 and evening summary at 21:00 Asia/Tashkent.
- Prayer time cache and prayer reminders.
- Quran progress tracking and daily goal follow-up.
- Siyam explicit toggle and Monday/Thursday heuristic fallback.
- Family contact reminder candidates without auto-creation.
- Boss/critical alert loop for marked urgent tasks.

## Broken or Incomplete Parts

- No proper test suite found.
- `.env.example` is empty.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; most previous mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake marker strings are intentional.
- No DB migration tool is visible; schema changes rely on `create_all()`.
- Crisis trigger tries to filter by `Task.user_id`, but `Task` model has no `user_id`; code logs and skips this trigger.
- Family layer is candidate/log oriented, not a full task lifecycle.
- Later Inbox, `/later`, `/focus`, `/backlog`, `/boss`, owner approval workflow, and full evening/morning planning engines are not visible as complete command surfaces.

## Production Readiness

Not production-ready yet.

Blocking items:

- Add configuration examples without secrets.
- Add smoke/import tests and core behavior tests.
- Keep UTF-8 checks for Telegram messages and avoid reading source through Windows Default encoding.
- Decide migration strategy.
- Validate Google OAuth/token paths and Docker volume setup on target VPS.
- Verify scheduler recovery and alert idempotency under restart.
