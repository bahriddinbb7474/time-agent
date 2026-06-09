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
- Stage 9 Prayer Protected Scheduling hardening is complete.
- Stage 10 Focus / Crisis Mode is complete.
- Stage 11 Evening Planning Engine is complete.
- Stage 12 Morning Briefing Upgrade is complete.
- Stage 13 Google Calendar Read-First Sync is complete.
- Stage 14 DailyPlan / completed_at lifecycle is complete in code and temp-DB tests; production DB migration has not been run.
- Stage 15 Voice Capture / AI Advisor Foundation is complete; real STT/AI providers are still disabled.

## What Works in Code

- Owner-only Telegram access.
- `/start`, `/rules`, `/today`, `/add`, `/edit`, `/delete`, `/done`, `/later`, `/backlog`, `/boss`, `/focus`, `/crisis`, `/plan_tomorrow`.
- Plain free-text Telegram messages create an in-memory pending capture draft and ask for confirmation before saving.
- Capture confirmations can save as a normal task, Later Inbox item, or Boss task through existing services.
- Voice messages are accepted safely, but transcription is disabled.
- Disabled STT and AI Advisor provider interfaces exist; no real provider calls are made.
- Minimal `✅ Сделал` button from `/today` marks tasks done through `task_done:<id>`.
- Later Inbox uses existing `tasks` rows with `status="later"` and is shown in evening summary.
- `/health` owner-only runtime status command.
- Google Calendar OAuth, read today/tomorrow, debug, pull/import-local reconcile, advisory conflicts, and write-capable methods gated off by default.
- `ENABLE_GOOGLE_WRITES=false` is the default production-safe policy; local task changes remain local-only unless explicitly enabled later.
- Prayer times fetch/cache and prayer reminder alerts.
- Context validation for sleep, second sleep, prayer, protected slots, and Siyam heavy-load warnings.
- Prayer protected scheduling uses Hanafi `school=1`, `Asia/Tashkent`, 15-minute pre-prayer and 20-minute post-prayer windows, plus Dhuhr `13:00-13:20`.
- `/add` and `/edit` warn on prayer conflicts and suggest safe slots without silent scheduling.
- Quran follow-up and hydration notifications are quieted during cached prayer protected windows.
- `/focus` suggests one deterministic active task; `/crisis` shows an urgent stack when 2+ urgent active tasks exist.
- `/today` includes a short focus/crisis hint; `/done` and `task_done:<id>` can suggest the next focus.
- First local done marks `Task.completed_at`; repeated done keeps the original completion time.
- Minimal `DailyPlan` model and service store manual daily plans.
- Morning briefing and evening summary jobs.
- Evening summary is now a short 21:00 planning session with done-today from `completed_at`, unfinished tasks, Later Inbox, focus/crisis hint, tomorrow local tasks, Quran/health/prayer status, read-only Google Calendar tomorrow context, and `Что главное завтра?`.
- Morning briefing is now a short 08:30 ready plan with saved DailyPlan text when present, local today tasks, soft focus/crisis context, read-only Google Calendar today context, prayer status, Quran/health/siyam context, and a gentle Later Inbox count.
- Quran progress and follow-up reminders.
- Basic family contact candidate generation.
- Boss/critical persistent alert queue.

## Key Risks

- No full automated pytest/unittest suite found.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; earlier broad mojibake output was a console decoding artifact.
- Telegram user-facing Russian strings are readable as UTF-8; `src/app/scheduler/jobs.py` mojibake markers are intentional.
- A Stage 14 schema migration exists in `migrations/versions/`, but no runner exists and it has not been applied to production `data/app.db`.
- Google Calendar service methods remain write-capable, but task sync write paths are gated by `ENABLE_GOOGLE_WRITES=false` by default.
- Marking tasks done is local-only; Google Calendar lifecycle behavior for done/cancelled/later is not implemented.
- Later Inbox is local-only; free-text capture can save into it after confirmation.
- Pending capture drafts are in-memory and disappear on restart.
- Voice transcription is disabled; no real STT provider or file download is implemented.
- AI Advisor is disabled; no real AI provider, autonomous decision, or AI planning is implemented.
- Boss alert cleanup on task done is still a follow-up.
- Persistent crisis stack DB flow is not implemented yet.
- Focus/crisis mode is deterministic only: no AI planning and no autonomous rescheduling.
- DailyPlan storage is manual only; no AI-generated plans, no automatic task moving, and no reopen flow exist yet.
- Old tasks completed before Stage 14 have no historical `completed_at`.
- Owner still creates tomorrow tasks manually with `/add`, `/later`, or `/boss`.
- Morning/evening Google conflict hints are advisory only; no local task moving and no Google event changes are performed.
- Boss alert suppression during prayer is unresolved and not implemented.
- Google Calendar imported-event prayer conflict review remains future work.
- Prayer window settings are code-level constants, not DB-backed settings.
- Crisis mode references `Task.user_id`, but the current `Task` model has no `user_id` column, so that path is effectively skipped.

## Next Priority

Next priority depends on owner choice: apply the Stage 14 DB migration to production only after backup and explicit approval, then continue Family/Relationship Layer, remaining lifecycle work, or owner-approved real STT/AI provider integration. Track: persistent capture drafts, reopen flow, promote Later items, later/postpone/cancel semantics, richer buttons, persistent crisis stack flow, boss alert cleanup on done, boss prayer suppression decision, and richer Google conflict actions.
