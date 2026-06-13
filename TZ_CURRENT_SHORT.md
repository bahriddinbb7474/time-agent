# Time-Agent v1 Target

Time-Agent v1 is a Telegram-first Personal Mental Load Dispatcher.

## Core Flow

capture -> organize -> remind -> protect -> plan -> review

## Target Behavior

- Telegram is the primary interface.
- Owner-only access is mandatory.
- Quick captures go into tasks or Later Inbox.
- `/later` opens unprocessed captures.
- `/boss` handles boss/critical priority flows.
- `/focus` starts focused execution mode.
- `/backlog` reviews unfinished and unscheduled work.
- Prayer protected windows block or warn before scheduling.
- Google Calendar is read-first; writes are policy-gated and owner-approved.
- Evening planning reviews today, prepares tomorrow, and asks for approval.
- Morning briefing presents the day plan and conflicts.
- Family/relationship reminders are suggested, not silently created.
- Health/Siyam/Quran state influences reminders and planning.
- VPS deployment must support 24/7 operation, persistent data, logs, secrets, and restart recovery.

## v1 Scope Marker

The final v1 should feel like a private dispatcher that captures mental load, protects non-negotiable priorities, schedules only after context checks, and keeps the owner in control of sensitive or external changes.
