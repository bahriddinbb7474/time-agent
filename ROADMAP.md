# Roadmap to Time-Agent v1

## Stage Status

- Stage 6 Stabilization Gate: done.
- Stage 7 local done/button slice: done.
- Stage 8 Capture Mode + Later Inbox: done.
- Stage 9 Prayer Protected Scheduling hardening: done.
- Stage 10 Focus / Crisis Mode: done.
- Stage 11 Evening Planning Engine: done.
- Stage 12 Morning Briefing Upgrade: done.
- Stage 13 Google Calendar Read-First Sync: done.
- Next stage: Family/Relationship Layer or remaining lifecycle semantics, depending on owner priority.

## 1. Stabilization Gate

- Completed: root docs, mojibake fix, `.env.example`, safe test DB, migration foundation, debug gates, Docker/env audit, and `/health` baseline.
- Remaining later: broader smoke/import tests, alert recovery verification, and a migration runner or Alembic decision before production schema changes.

## 2. Task Lifecycle + Buttons

- Completed: safe temp-DB task status smoke test.
- Completed: local-only `done` status update.
- Completed: `/done <id>` command.
- Completed: `/today` hides `done` and `cancelled` tasks from active timed/floating lists.
- Completed: minimal Telegram `✅ Сделал` button using `task_done:<id>`.
- Remaining: postponed/later/cancelled semantics, edit/delete/reschedule buttons, boss alert cleanup on task done, and Google Calendar lifecycle policy.

## 3. Capture Mode + Later Inbox

- Completed: Later Inbox stored in existing `tasks` table with `status="later"`.
- Completed: `/later <text>` saves local-only inbox items.
- Completed: `/backlog` shows Later Inbox items oldest first.
- Completed: `/boss <text>` creates a fast floating work task.
- Completed: evening summary shows a short Later Inbox section.
- Completed: `/add` today/tomorrow parser literals were cleaned up.
- Remaining: richer inbox review buttons, promotion from Later to scheduled task, and owner approval workflow.

## 4. Prayer Protected Scheduling

- Completed: pure prayer protected-window helper with Hanafi/Tashkent constants.
- Completed: ContextValidator uses cached prayer times for read-only validation when cache exists.
- Completed: prayer conflict tests for protected windows, Dhuhr dead zone, safe-slot suggestion, and completed-prayer skip.
- Completed: `/add` and `/edit` prayer conflict UX hardened to avoid silent scheduling.
- Completed: Quran follow-up and hydration quieting during cached prayer protected windows.
- Completed: prayer reminder wording now says to prepare before prayer.
- Completed: prayer alert idempotency/stale smoke coverage.
- Remaining: boss alert prayer suppression decision, DB-backed prayer window settings later, and Google Calendar imported-event prayer conflict review.

## 5. Focus/Crisis Mode

- Completed: deterministic urgent detection for active `todo` tasks.
- Completed: pure focus selector with no DB writes.
- Completed: active focus candidate query using the existing `tasks` table.
- Completed: `/focus` command surface.
- Completed: `/crisis` command surface for 2+ urgent active tasks.
- Completed: short `/today` focus/crisis hint.
- Completed: next-focus suggestion after `/done` and `task_done:<id>`.
- Remaining: persistent crisis stack DB flow, user-scoped crisis stacks, boss alert cleanup on task done, and richer focus buttons.

## 6. Evening Planning Engine

- Completed: evening summary is now a short 21:00 planning flow.
- Completed: review includes unfinished tasks, Later Inbox, focus/crisis hint, tomorrow local tasks, Quran status, prayer status, health/siyam context, and read-only Google Calendar tomorrow context.
- Completed: final prompt asks `Что главное завтра?`.
- Completed: Quran follow-up alert reuse has a temp-DB regression check.
- Remaining: no `DailyPlan` storage, no `completed_at`/done-today tracking, and no silent task moving or automatic tomorrow task creation.

## 7. Morning Briefing

- Completed: morning briefing is now a short ready plan for today.
- Completed: includes local today tasks, soft focus/crisis context, prayer status, Quran/health/siyam context, read-only Google Calendar today context, and a gentle Later Inbox count.
- Completed: keeps the existing 08:30 scheduler and debug-gated `/test_brief` trigger.
- Remaining: no `DailyPlan` storage, no `completed_at`/done-today tracking, no AI planning, no Google writes, and no silent rescheduling.
- Later: consume stored evening plan only after a storage/approval model is designed.

## 8. Google Calendar Read-First Sync

- Completed: normalized fake-tested Google event formatter for Telegram-safe output.
- Completed: `ENABLE_GOOGLE_WRITES=false` default gate prevents task sync create/update/delete calls to Google Calendar.
- Completed: `/gcal_today` uses read-only normalized `list_events()`.
- Completed: `/gcal_tomorrow` uses the same read-only path.
- Completed: pure advisory conflict detector for Google event vs local timed task and Google event vs prayer protected window.
- Completed: `/gcal_conflicts` reports today's advisory conflicts and requires owner action.
- Completed: morning/evening Google sections can show a short conflict-count hint.
- Completed: `/gcal_pull` text clarifies read/import-local behavior and no Google writes.
- Remaining: richer Google conflict action buttons, preview-only import mode if desired, and deeper reconciliation tests for echo/import/update/delete failure cases.

## 9. Family/Relationship Layer

- Promote family contact candidates into owner-approved tasks.
- Add contact completion tracking.
- Preserve privacy by keeping family tasks local-only.

## 10. Health/Siyam/Quran v1

- Stabilize Siyam explicit and heuristic policy.
- Suppress hydration during daylight on Siyam days.
- Complete Quran daily goal review and follow-up.
- Add low-energy mode behavior.

## 11. VPS Production 24/7

- Adapt secrets path for VPS and verify `/run/secrets` read-only mount.
- Keep `/app/data` persistent and document SQLite/token backup and restore.
- Add Docker healthcheck or external heartbeat/monitoring around the Telegram `/health` baseline.
- Verify OAuth callback port and redirect URI.
- Confirm `TZ=Asia/Tashkent`, `ENABLE_DEBUG_COMMANDS=false`, logging mode, and restart policy.
- Add operational smoke checklist.

## 12. Voice Capture v1.1

- Add voice-to-text capture after v1 core is stable.
- Route voice captures into Later Inbox first.

## 13. Optional Web UI v2

- Add web dashboard only after Telegram v1 is stable.
- Keep Telegram as primary control surface.
