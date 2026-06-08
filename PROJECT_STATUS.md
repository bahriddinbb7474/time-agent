# Project Status

## Current Stage

Stage 8 Capture Mode + Later Inbox is complete. The project remains pre-production, but root docs, env examples, safe test DB, migration foundation, debug gates, Docker/env audit, `/health`, local task done status, `/done`, active `/today` filtering, a minimal Telegram done button, Later Inbox, `/later`, `/backlog`, `/boss`, and evening Later review are now in place.

## Working Features Visible in Code

- Telegram bot startup and polling through aiogram.
- Owner-only access control using `ALLOWED_TELEGRAM_ID`.
- SQLite persistence through SQLAlchemy async.
- Default protected slots and routines seeding.
- Task creation, editing, deletion, local done marking, Later Inbox capture, boss capture, and daily active listing.
- Context validation for sleep, second sleep, prayer windows, protected slots, and Siyam heavy-load warnings.
- Google Calendar OAuth, event reads, pull/reconcile, and category-limited write sync.
- Persistent alert queue with recovery after restart.
- Morning briefing at 08:30 and evening summary at 21:00 Asia/Tashkent.
- Prayer time cache and prayer reminders.
- Quran progress tracking and daily goal follow-up.
- Siyam explicit toggle and Monday/Thursday heuristic fallback.
- Family contact reminder candidates without auto-creation.
- Boss/critical alert loop for marked urgent tasks.
- Production debug/test commands are gated by `ENABLE_DEBUG_COMMANDS`.
- Owner-only `/health` command reports safe runtime status.
- Safe OAuth state smoke test uses an isolated temporary SQLite DB.
- Safe task status smoke test uses an isolated temporary SQLite DB.
- Safe Later Inbox smoke test uses an isolated temporary SQLite DB.

## Broken or Incomplete Parts

- No full pytest/unittest suite found.
- `.env.example` contains placeholder-only runtime values; no real secrets should be committed.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; most previous mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake marker strings are intentional.
- Migration foundation is documented in `migrations/`; no schema-changing migrations exist yet, and startup still calls `create_all()`.
- Crisis trigger tries to filter by `Task.user_id`, but `Task` model has no `user_id`; code logs and skips this trigger.
- Family layer is candidate/log oriented, not a full task lifecycle.
- Local task `done` and Later Inbox `status="later"` capture are implemented; `moved`, `skipped`, `postponed`, and `cancelled` task lifecycle semantics are not implemented yet.
- Marking a task done is local-only and does not update/delete Google Calendar events.
- Later Inbox appears in evening summary, but full evening/morning planning engines and owner approval workflow are not complete.
- `/focus` is not visible as a complete command surface.

## Production Readiness

Not production-ready yet.

Docker/env/secrets safe now:

- Docker runs the bot as non-root `appuser`.
- `/app/data` is persisted through the `app_data` volume.
- `./logs` is mounted to `/app/logs`; file logging remains opt-in.
- `/run/secrets` is mounted read-only from the host.
- Google credentials/token paths are configurable through env.
- `TZ=Asia/Tashkent` is set in Compose and supported by container `tzdata`.
- `restart: always` is configured.
- Debug/test commands default to disabled.

Blocking items:

- Add remaining task lifecycle semantics, including later/postpone/cancel policy and Google Calendar lifecycle decisions.
- Keep UTF-8 checks for Telegram messages and avoid reading source through Windows Default encoding.
- Add a migration runner or Alembic decision before production schema evolution.
- Validate Google OAuth/token paths and Docker volume setup on target VPS.
- Add Docker healthcheck or external heartbeat/monitoring.
- Extend health checks with external heartbeat if needed.
- Document SQLite and Google token backup/restore.
- Replace Windows-specific secrets mount with VPS-specific path.
- Verify scheduler recovery and alert idempotency under restart.
