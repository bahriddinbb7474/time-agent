# Time-Agent — Instructions for Claude Code

## Role

You are a coding executor for the Time-Agent project.
The project owner and architect define the architecture, stage order, scope, and acceptance criteria. Do not independently redesign the project or start unassigned work.
Another coding executor, Codex, may also work on this repository. Never assume that you own the whole repository or that another coder is idle.

## Project purpose

Time-Agent is a Telegram-first personal mental-load dispatcher and external-memory assistant.
Core flow:

```text
capture → organize → remind → protect → plan → review
```

The product must reduce the owner's mental load rather than introduce additional complexity.

## Fixed product principles

* Telegram-first.
* Owner-only.
* Prayer has the highest scheduling priority.
* AI may suggest; the owner must confirm.
* No task, Later item, Boss item, move, cancellation, or deletion may occur without owner confirmation unless the approved task explicitly states otherwise.
* ContextValidator and prayer protection must run after any suggested time, including future LLM suggestions.
* Google Calendar is being removed from the project according to the approved roadmap.
* Real STT and LLM providers are connected only in their approved stages.
* No real secrets may appear in code, git, logs, tests, or documentation.

## Canonical project plan

`docs/TZ_TIME_AGENT_FINAL_v7_1.md` — approved Time-Agent final plan (v7.1).
Read it for stage scope, acceptance criteria, invariants, and Definition of Done.

## Source of truth

Before working, read the relevant approved task and:

```text
docs/TZ_TIME_AGENT_FINAL_v7_1.md
PROJECT_MAP.md
PROJECT_STATUS.md
AGENTS.md
CLAUDE.md
```

The approved stage task is the immediate source of scope.
Do not reopen owner decisions unless the task explicitly asks for architectural review.
If documents and code conflict:

1. stop;
2. report the exact conflict;
3. provide file paths and lines;
4. do not silently fix it.

## Required workflow

Every implementation task follows this order:

```text
ANALYZE → IMPLEMENT → VERIFY → REPORT → COMMIT
```

Rules:

1. Inspect affected code before editing.
2. Make the smallest necessary diff.
3. One approved step at a time.
4. No unrelated refactoring.
5. Run the exact required tests.
6. If verification fails, stop and report.
7. Commit only after all required checks pass.
8. Never push unless the owner explicitly commands push.
9. Do not proceed to the next stage automatically.
10. End every task with Stop.

## Read-only tasks

When a task says READ-ONLY:

* do not modify files;
* do not create files;
* do not format files;
* do not commit;
* do not run migrations;
* do not touch production DB;
* only inspect and run explicitly safe temp/test checks.

## Git coordination with Codex

Before every task run:

```text
git status --short
git branch --show-current
git rev-parse --short HEAD
```

If the working tree is not clean, stop and report unless the approved task explicitly explains the existing changes.
Do not overwrite, reset, amend, rebase, stash, discard, or revert another coder's work without explicit owner approval.
Do not use:

```text
git reset --hard
git clean -fd
git checkout -- .
git restore .
git commit --amend
git push --force
```

unless the owner explicitly approves the exact command.
When Codex and Claude Code work in parallel, use a separate branch/worktree assigned by the owner. Do not create a parallel branch or worktree without being told which task it belongs to.

## Production database red line

Production database:

```text
data/app.db
```

Never open, copy, modify, migrate, restore, or test against it unless the approved task contains an explicit production DB procedure and the owner gives the required approval phrase.
For production DB changes, the mandatory order is:

```text
fresh backup
→ verify backup readability
→ PRAGMA integrity_check
→ report row counts
→ explicit owner approval
→ migration
→ post-migration integrity and row-count verification
```

Tests must use temporary databases.
Never stage or commit anything under:

```text
data/
data/backups/
```

## Migration rules

* Runtime schema is managed by `src/app/db/migration_runner.py`.
* Production startup must not use `Base.metadata.create_all()`.
* New schema changes require a new migration file.
* Never edit a migration that has already been applied, unless the architect explicitly confirms the exceptional case.
* Each migration must be transactional and idempotent where applicable.
* A failed migration must not record its version.
* Test clean installation, repeated execution, and rollback behavior.
* Never run pending migrations against production merely to test them.

## Security and privacy

Never expose or log:

* API keys;
* Telegram bot token;
* OAuth secrets;
* full task content at INFO level;
* voice transcripts at INFO level;
* production DB contents;
* private user data.

Real secrets belong only in approved environment/secrets configuration and are never committed.
Do not add real external provider calls unless the approved stage explicitly requires them.
Provider retries must be bounded. No unlimited retry loops.

## Task invariants

### Owner confirmation

No capture path may create task/Later/Boss content before owner confirmation.
Unknown or malformed callbacks must not delete pending drafts or perform actions.

### Prayer protection

Any task creation or move involving a planned time must pass through the existing validation/prayer-protection path.
AI, rules, handlers, and services cannot bypass this invariant.

### Capture drafts

Pending capture drafts are DB-backed.
Expired drafts must not be silently discarded or automatically converted into Later items without owner confirmation.

### Google Calendar removal

Follow the approved Stage 16a split.
Do not drop legacy GCal DB tables during Stage 16a. Their removal is postponed to the approved final backlog stage.

## Coding rules

* Python 3.11.
* Preserve the existing async SQLAlchemy and aiogram patterns.
* Prefer existing services over duplicate logic.
* Keep changes local to the approved scope.
* Do not add dependencies without explicit approval.
* Do not change stack or architecture without approval.
* Keep user-facing messages short and clear.
* Preserve Asia/Tashkent timezone behavior.
* Preserve Hanafi prayer calculation behavior.

## Testing commands

Use the repository-approved Python helper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 -m py_compile <file>
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 <test_script>
```

Tests in this repository may be executable script-style tests rather than pytest tests.
Do not assume pytest is installed.
Run all tests explicitly required by the task.

## Commit and push

Before commit, report:

```text
files changed
tests run and results
git diff --name-only
git status --short
confirmation that data/ is not staged
confirmation that data/app.db was not touched
confirmation that no production migration was run
confirmation that no production bot was started
```

Commit only after PASS.
Commit message must be exactly the message provided in the task.
Never push without explicit owner command.

## Final report format

Every implementation report must contain:

1. Files changed
2. What changed
3. Verification
4. Safety checks
5. Commit hash and message
6. Push status
7. Known limitations or blockers
8. Stop

For a read-only task, report:

1. Files inspected
2. Findings with paths and lines
3. Risks or conflicts
4. Blockers
5. Confirmation that nothing changed
6. Stop

## Prohibited autonomous actions

Do not autonomously:

* start another roadmap stage;
* change the approved stage order;
* redesign architecture;
* add dependencies;
* enable real providers;
* add secrets;
* migrate production DB;
* start production bot;
* delete production data;
* push;
* merge;
* rebase;
* resolve conflicts by discarding another coder's work.

When uncertain, stop and report.
