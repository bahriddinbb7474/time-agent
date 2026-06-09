# Project Status

## Current Stage

Stage 14 DailyPlan / completed_at lifecycle is complete in code and temp-DB tests. The project remains pre-production, but root docs, env examples, safe test DB, migration foundation, debug gates, Docker/env audit, `/health`, local task done status, `/done`, active `/today` filtering, a minimal Telegram done button, Later Inbox, `/later`, `/backlog`, `/boss`, prayer protected scheduling hardening, `/focus`, `/crisis`, the 21:00 evening planning summary, the 08:30 morning ready-plan briefing, Google Calendar read-first safeguards, `Task.completed_at`, minimal `DailyPlan`, and `/plan_tomorrow` are now in place.

## Working Features Visible in Code

- Telegram bot startup and polling through aiogram.
- Owner-only access control using `ALLOWED_TELEGRAM_ID`.
- SQLite persistence through SQLAlchemy async.
- Default protected slots and routines seeding.
- Task creation, editing, deletion, local done marking with `completed_at`, Later Inbox capture, boss capture, and daily active listing.
- Minimal `DailyPlan` storage and `/plan_tomorrow <text>` manual save/upsert for tomorrow.
- Deterministic focus/crisis selection for active `todo` tasks.
- `/focus` suggests one next task; `/crisis` shows an urgent stack when 2+ urgent active tasks exist.
- `/today` shows a short focus/crisis hint when useful.
- `/done` and `task_done:<id>` suggest the next focus task when one remains.
- Context validation for sleep, second sleep, prayer windows, protected slots, and Siyam heavy-load warnings.
- Prayer protected windows use Hanafi `school=1`, `Asia/Tashkent`, 15 minutes before prayer, 20 minutes after prayer, and the Dhuhr `13:00-13:20` dead zone.
- `/add` and `/edit` do not silently create/update tasks inside prayer conflicts; they warn and suggest a safe slot when available.
- Quran follow-up alerts are postponed during cached prayer protected windows; hydration runtime pings are skipped during cached prayer protected windows.
- Google Calendar OAuth, normalized event reads, `/gcal_today`, `/gcal_tomorrow`, `/gcal_conflicts`, pull/import-local reconcile, and read-first write gate.
- Google Calendar event writes are disabled by default through `ENABLE_GOOGLE_WRITES=false`.
- Persistent alert queue with recovery after restart.
- Morning briefing at 08:30 and evening summary at 21:00 Asia/Tashkent.
- Morning briefing now acts as a short ready plan for today with saved DailyPlan text when present, local tasks, soft focus/crisis context, read-only Google Calendar today context, prayer status, Quran/health/siyam context, and a gentle Later Inbox count.
- Evening summary now acts as a short planning session with done-today from `completed_at`, unfinished tasks, Later Inbox, focus/crisis hint, tomorrow local tasks, Quran/health/prayer status, read-only Google Calendar tomorrow context, and the prompt `Что главное завтра?`.
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
- Safe prayer validation/recovery smoke test uses an isolated temporary SQLite DB.
- Safe focus/crisis smoke test uses an isolated temporary SQLite DB.
- Safe evening planning smoke test uses an isolated temporary SQLite DB.
- Safe morning briefing smoke test uses an isolated temporary SQLite DB.
- Safe DailyPlan/completed_at lifecycle and migration smoke tests use isolated temporary SQLite DBs.

## Broken or Incomplete Parts

- No full pytest/unittest suite found.
- `.env.example` contains placeholder-only runtime values; no real secrets should be committed.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; most previous mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake marker strings are intentional.
- A schema-changing migration exists in `migrations/versions/20260609_1300_add_daily_plan_lifecycle.sql`, but it has not been run on production `data/app.db`; startup still calls `create_all()`.
- Persistent crisis stack DB flow is not implemented yet.
- Crisis trigger tries to filter by `Task.user_id`, but `Task` model has no `user_id`; code logs and skips this trigger.
- Family layer is candidate/log oriented, not a full task lifecycle.
- Local task `done`, `completed_at`, and Later Inbox `status="later"` capture are implemented; `moved`, `skipped`, `postponed`, and richer `cancelled` task lifecycle semantics are not implemented yet.
- Marking a task done is local-only and does not update/delete Google Calendar events.
- Evening planning reads done-today from `completed_at`, but old tasks completed before Stage 14 have no completion timestamp.
- DailyPlan storage is manual through `/plan_tomorrow`; there is no AI plan generation or automatic task moving.
- Morning briefing consumes DailyPlan for today only when one exists.
- Owner still creates tomorrow tasks manually with `/add`, `/later`, or `/boss`.
- Morning briefing has no AI planning and does not move/reschedule tasks.
- Morning Google Calendar context is read-only and degrades quietly when unavailable.
- Later Inbox appears in morning only as a gentle count.
- Boss alert suppression during prayer is intentionally unresolved and not implemented.
- Boss alert cleanup on task done is still separate from focus/crisis mode.
- Focus/crisis mode does not use AI planning and does not autonomously reschedule tasks.
- DB-backed prayer window settings are not implemented; Stage 9 uses code-level constants.
- Google Calendar write-capable service methods still exist, but task sync write paths are gated by config and disabled by default.
- `/gcal_pull` still writes local DB rows when importing/reconciling Google events; it does not write Google Calendar.
- Google conflict reporting is advisory only; no local task moving and no Google event changes are performed.
- No Google conflict action buttons were added in Stage 13.

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
- Google Calendar writes default to disabled.

Blocking items:

- Add remaining task lifecycle semantics, including later/postpone/cancel policy and Google Calendar lifecycle decisions.
- Back up production SQLite and get explicit owner approval before applying the Stage 14 schema migration to `data/app.db`.
- Keep UTF-8 checks for Telegram messages and avoid reading source through Windows Default encoding.
- Add a migration runner or Alembic decision before production schema evolution.
- Validate Google OAuth/token paths and Docker volume setup on target VPS.
- Add Docker healthcheck or external heartbeat/monitoring.
- Extend health checks with external heartbeat if needed.
- Document SQLite and Google token backup/restore.
- Replace Windows-specific secrets mount with VPS-specific path.
- Verify scheduler recovery and alert idempotency under restart.
