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

## What Works in Code

- Owner-only Telegram access.
- `/start`, `/rules`, `/today`, `/add`, `/edit`, `/delete`, `/done`, `/later`, `/backlog`, `/boss`, `/focus`, `/crisis`.
- Minimal `✅ Сделал` button from `/today` marks tasks done through `task_done:<id>`.
- Later Inbox uses existing `tasks` rows with `status="later"` and is shown in evening summary.
- `/health` owner-only runtime status command.
- Google Calendar OAuth, read today, debug, pull/reconcile, create/update/delete for allowed task categories.
- Prayer times fetch/cache and prayer reminder alerts.
- Context validation for sleep, second sleep, prayer, protected slots, and Siyam heavy-load warnings.
- Prayer protected scheduling uses Hanafi `school=1`, `Asia/Tashkent`, 15-minute pre-prayer and 20-minute post-prayer windows, plus Dhuhr `13:00-13:20`.
- `/add` and `/edit` warn on prayer conflicts and suggest safe slots without silent scheduling.
- Quran follow-up and hydration notifications are quieted during cached prayer protected windows.
- `/focus` suggests one deterministic active task; `/crisis` shows an urgent stack when 2+ urgent active tasks exist.
- `/today` includes a short focus/crisis hint; `/done` and `task_done:<id>` can suggest the next focus.
- Morning briefing and evening summary jobs.
- Evening summary is now a short 21:00 planning session with unfinished tasks, Later Inbox, focus/crisis hint, tomorrow local tasks, Quran/health/prayer status, read-only Google Calendar tomorrow context, and `Что главное завтра?`.
- Morning briefing is now a short 08:30 ready plan with local today tasks, soft focus/crisis context, read-only Google Calendar today context, prayer status, Quran/health/siyam context, and a gentle Later Inbox count.
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
- Persistent crisis stack DB flow is not implemented yet.
- Focus/crisis mode is deterministic only: no AI planning and no autonomous rescheduling.
- Evening planning is message-only: no `DailyPlan` storage, no `completed_at`/done-today tracking, and no stored evening output for morning briefing yet.
- Owner still creates tomorrow tasks manually with `/add`, `/later`, or `/boss`.
- Morning briefing does not use AI planning, does not write Google Calendar, and does not silently reschedule tasks.
- Boss alert suppression during prayer is unresolved and not implemented.
- Google Calendar imported-event prayer conflict review remains future work.
- Prayer window settings are code-level constants, not DB-backed settings.
- Crisis mode references `Task.user_id`, but the current `Task` model has no `user_id` column, so that path is effectively skipped.

## Next Priority

Google Calendar Read-First Sync, while tracking remaining lifecycle work: promote Later items, later/postpone/cancel semantics, richer buttons, persistent crisis stack flow, boss alert cleanup on done, boss prayer suppression decision, Google Calendar lifecycle policy, and a future storage/approval model for evening plans.
