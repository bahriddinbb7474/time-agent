# Roadmap to Time-Agent v1

## 1. Stabilization Gate

- Fix documentation/config mismatch, especially `.env.example`.
- Add smoke tests for imports, startup configuration, DB initialization, and scheduler construction.
- Keep UTF-8 checks for Russian Telegram messages; avoid treating Windows console decoding artifacts as source corruption.
- Verify alert queue recovery and idempotent send behavior.
- Add a migration runner or make an explicit Alembic decision before production schema changes; `create_all()` remains startup safety only.

## 2. Task Lifecycle + Buttons

- Complete task status lifecycle: todo, done, cancelled, postponed.
- Add Telegram inline buttons for done, postpone, reschedule, delete, and edit flows.
- Ensure Google external link state follows local lifecycle.

## 3. Capture Mode + Later Inbox

- Add quick capture for unstructured messages.
- Add Later Inbox storage and commands.
- Implement `/later` and inbox review flow.

## 4. Prayer Protected Scheduling

- Harden prayer protected windows and Dhuhr special case.
- Ensure prayer completion affects later scheduling.
- Add tests for Hanafi Tashkent timings, protected buffers, and stale alert recovery.

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

- Finalize `.env.example`, secrets paths, volumes, restart policy, logging, and backup notes.
- Verify OAuth callback port and redirect URI.
- Add operational smoke checklist.

## 12. Voice Capture v1.1

- Add voice-to-text capture after v1 core is stable.
- Route voice captures into Later Inbox first.

## 13. Optional Web UI v2

- Add web dashboard only after Telegram v1 is stable.
- Keep Telegram as primary control surface.
