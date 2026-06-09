# Roadmap to Time-Agent v1

## Stage Status

- Stage 6 Stabilization Gate: done.
- Stage 7 local done/button slice: done.
- Stage 8 Capture Mode + Later Inbox: done.
- Stage 9 Prayer Protected Scheduling hardening: done.
- Next stage: Evening Planning Engine or Focus/Crisis Mode, with remaining lifecycle semantics tracked separately.

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

- Implement `/focus` command surface.
- Complete crisis stack persistence and user scoping.
- Add rules for urgent overload, next-action selection, and recovery to normal mode.

## 6. Evening Planning Engine

- Turn evening summary into planning flow.
- Review unfinished tasks, Quran status, prayer status, health context, and tomorrow candidates.
- Require owner approval before creating or moving tasks.

## 7. Morning Briefing

- Expand morning briefing into actionable daily plan.
- Include protected slots, prayer windows, Google Calendar read view, Later Inbox, and top priorities.
- Add buttons to accept, adjust, or defer.

## 8. Google Calendar Read-First Sync

- Make Google pull/reconcile the default safe path.
- Keep work-sync policy explicit.
- Add conflict review and safe-slot proposals before writes.
- Add tests for echo skipping, imported events, conflicts, and delete/update failures.

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
