# Tests Log

## Existing Tests Found

- No pytest/unittest suite found.
- `src/app/db/test_oauth_state_repo.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_task_status.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_later_inbox.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_prayer_validation.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_focus_crisis.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_evening_planning.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_morning_briefing.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_daily_plan_lifecycle.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_daily_plan_migration.py` is a temp SQLite migration smoke test.
- `src/app/db/test_capture_classification.py` is a pure capture classification smoke test.
- `src/app/db/test_capture_confirmation.py` is a pure capture confirmation helper smoke test.
- `src/app/db/test_capture_actions.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_stt_provider.py` is a disabled STT provider smoke test.
- `src/app/db/test_ai_advisor_provider.py` is a disabled AI Advisor provider smoke test.
- Handler names `test_brief_cmd` and `test_evening_cmd` are Telegram command handlers, not tests.

## Tests Run

Safe manual DB smoke command:

```powershell
$env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_oauth_state_repo.py
```

This command must use a temporary SQLite DB and must not touch `data/app.db`.

Safe task status smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_task_status.py
```

This verifies local task `done` marking and active `/today` filtering against a temporary SQLite DB only.

Safe Later Inbox smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_later_inbox.py
```

This verifies `status="later"` storage, `list_later()`, exclusion from active `/today`, and `/add` today/tomorrow parser literals against a temporary SQLite DB only.

Safe prayer validation/recovery smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_prayer_validation.py
```

This verifies Hanafi/Tashkent constants, prayer protected-window conflicts, Dhuhr dead zone, safe-slot suggestion, completed-prayer skip, cached read-only validation, prayer quieting, no duplicate prayer alerts, and stale prayer alert detection against a temporary SQLite DB only.

Safe focus/crisis smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_focus_crisis.py
```

This verifies urgent detection, active filtering excluding `done`/`cancelled`/`later`, focus selector behavior, crisis threshold behavior, and active focus candidate query against a temporary SQLite DB only.

Safe evening planning smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_evening_planning.py
```

This verifies evening planning source data, tomorrow local task query, formatter output, Later Inbox inclusion, focus hint input, Google Calendar tomorrow formatting input, and Quran follow-up alert reuse against a temporary SQLite DB only.

Safe morning briefing smoke command:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; $env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_morning_briefing.py
```

This verifies morning briefing source data, active today filtering, Later Inbox count, focus hint input, formatter output, Google Calendar today formatting input, and Google unavailable fallback against a temporary SQLite DB only.

Safe DailyPlan/completed_at lifecycle smoke command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_daily_plan_lifecycle.py
```

This verifies nullable `Task.completed_at`, idempotent `mark_done()`, done-today query, and DailyPlan save/read/upsert against a temporary SQLite DB only.

Safe DailyPlan migration smoke command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_daily_plan_migration.py
```

This applies the Stage 14 SQL migration to a temporary SQLite DB only and verifies `tasks.completed_at`, `daily_plans`, and `schema_migrations`.

Safe capture foundation smoke commands:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_capture_classification.py
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_capture_confirmation.py
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_capture_actions.py
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_stt_provider.py
powershell -ExecutionPolicy Bypass -File scripts\codex_python.ps1 src/app/db/test_ai_advisor_provider.py
```

These verify rule-based capture classification, confirmation helper callback data, confirmed capture actions against a temporary SQLite DB, disabled STT behavior, and disabled AI Advisor behavior.

Python note: the documented Python path requires existing `.venv\Lib\site-packages` on `PYTHONPATH` for project dependencies in this environment. `.venv\Scripts\python.exe` exists but its launcher is broken.

## Migration Verification

The Stage 14 migration file was tested only on a temporary SQLite DB. It was not run against production `data/app.db`.

## Debug Command Safety

`/test_brief`, `/test_evening`, and `/gcal_debug` are gated by `ENABLE_DEBUG_COMMANDS=false` by default.

## Docker / Env / Secrets Audit Verification

Safe inspection only. Bot was not started, migrations were not run, and `data/app.db` was not modified.

## Health Command Verification

`/health` was added as an owner-only Telegram command. Bot was not started; verification is limited to `py_compile` and safe source search.

## Stage 7 Task Lifecycle Verification

- Local task `done` marking passed isolated temp SQLite smoke test.
- Missing task and idempotent done behavior are covered by `src/app/db/test_task_status.py`.
- Active `/today` filtering hides `done` and `cancelled` timed tasks in the smoke test.
- `/done <id>` and `task_done:<id>` were verified with `py_compile` and safe source search.
- Bot was not started.

## Stage 8 Capture Mode Verification

- Later Inbox local storage passed isolated temp SQLite smoke test.
- Later items use `status="later"`, `planned_at=None`, `duration_min=30`, and category `other`.
- Later items are excluded from active `/today`.
- `/later`, `/backlog`, `/boss`, and evening Later summary were verified with `py_compile` and safe source search.
- `/add` today/tomorrow parser literal cleanup was covered by parser smoke in `src/app/db/test_later_inbox.py`.
- Bot was not started.

## Stage 9 Prayer Protected Scheduling Verification

- Prayer validation and alert recovery passed isolated temp SQLite smoke test.
- Protected windows keep Hanafi `school=1`, `Asia/Tashkent`, 15 minutes before prayer, and 20 minutes after prayer.
- Dhuhr dead zone remains `13:00-13:20` with suggested shift to `13:25`.
- Cached prayer validation avoids forced Aladhan refresh/write when prayer cache already exists.
- Quran follow-up quieting and hydration quieting use cached prayer times only.
- Boss alerts are not suppressed during prayer; this remains an owner decision.
- Bot was not started.

## Stage 10 Focus / Crisis Mode Verification

- Focus/crisis logic passed isolated temp SQLite smoke test.
- `/focus` and `/crisis` were verified by `py_compile` and safe source search.
- `/today` focus/crisis hint was verified by `py_compile`.
- `/done` and `task_done:<id>` next-focus suggestion was verified by `py_compile`.
- Persistent crisis stack DB flow was not implemented.
- Boss alert cleanup remains separate.
- No AI planning and no autonomous rescheduling were added.
- Bot was not started.

## Stage 11 Evening Planning Engine Verification

- Evening planning smoke test passed against an isolated temporary SQLite DB.
- The 21:00 evening summary uses a pure formatter and keeps Telegram sending in the scheduler job.
- Tomorrow local tasks are read through the existing `tasks` table and exclude `done`, `cancelled`, and `later`.
- Google Calendar tomorrow context is read-only and degrades quietly when credentials or access are unavailable.
- Quran follow-up alert reuse is covered by a regression check that keeps one active alert for the same day.
- No `DailyPlan` storage, `completed_at` tracking, AI planning, silent task moving, migrations, or production DB writes were added.
- Bot was not started.

## Stage 12 Morning Briefing Upgrade Verification

- Morning briefing smoke test passed against an isolated temporary SQLite DB.
- The 08:30 morning briefing uses a pure formatter and keeps Telegram sending in the scheduler job.
- Active today tasks exclude `done`, `cancelled`, and `later`.
- Later Inbox appears only as a gentle count.
- Google Calendar today context is read-only and degrades quietly when credentials or access are unavailable.
- No `DailyPlan` storage, `completed_at` tracking, AI planning, silent task moving, migrations, or production DB writes were added.
- Bot was not started.

## Stage 13 Google Calendar Read-First Sync Verification

- Google read-first smoke test passed with fake Google data and an isolated temporary SQLite DB.
- Event formatter covers timed, all-day, cancelled/no-output, capped Telegram-safe output, and hidden IDs/links.
- `ENABLE_GOOGLE_WRITES=false` gate prevents fake task-sync Google create/update/delete calls while keeping local task creation.
- `/gcal_today`, `/gcal_tomorrow`, and `/gcal_conflicts` were verified by `py_compile` and safe source search.
- Google conflict detector covers Google event vs local timed task and Google event vs cached prayer protected window.
- Morning and evening conflict hints were verified through existing smoke tests.
- `/gcal_pull` wording now clarifies read/import-local behavior and no Google writes.
- No real Google API calls were made in tests.
- No migrations, bot startup, silent rescheduling, AI planning, Google writes, or production DB writes were added.

## Stage 14 DailyPlan / completed_at Lifecycle Verification

- DailyPlan/completed_at lifecycle smoke test passed against an isolated temporary SQLite DB.
- Stage 14 migration smoke test passed against a temporary SQLite DB only.
- `mark_done()` sets `completed_at` on first done and keeps the original timestamp on repeated done.
- Done-today query uses `completed_at`; old done tasks without completion timestamps are not counted.
- `/plan_tomorrow <text>` saves/upserts tomorrow's manual DailyPlan.
- Morning briefing shows today's saved DailyPlan when present.
- Evening planning shows done-today from `completed_at`.
- Production `data/app.db` migration was not run.
- No AI planning, automatic task moving, Google Calendar behavior changes, real bot startup, or production DB writes were added.

## Stage 15 Voice Capture / AI Advisor Foundation Verification

- Capture classification smoke test passed with pure logic and no DB writes.
- Capture confirmation helper smoke test passed with short callback data.
- Capture actions smoke test passed against an isolated temporary SQLite DB.
- Plain free text creates only an in-memory pending draft until callback confirmation.
- Confirmed capture can save as normal task, Later Inbox item, or Boss task through existing services.
- Voice handler skeleton was verified by `py_compile`; it does not download/store voice files.
- Disabled STT provider smoke test passed with no external call.
- Disabled AI Advisor provider smoke test passed with no external call.
- No real STT provider, AI provider, bot startup, migrations, schema changes, Google Calendar behavior changes, autonomous decisions, or production DB writes were added.

## Stage 6 Closeout Verification

- Root info docs exist.
- The old mojibake `Starting bot` log variant is absent.
- `.env.example` contains placeholder-only values; no real secrets found.
- OAuth state smoke test passed with an isolated temporary SQLite DB.
- `data/app.db` timestamp was unchanged by the smoke test.
- Migration foundation files exist under `migrations/`.
- `ENABLE_DEBUG_COMMANDS` gates debug/test commands.
- `/health` is registered and documented.
- Bot was not started.

## Missing Critical Tests

- Import smoke test for all app modules.
- Config loading tests for missing/valid env.
- DB init and seed tests.
- Task create/edit/delete service tests beyond the current manual status/focus smoke.
- Handler-level tests for `/done` and `task_done:<id>`.
- Handler-level tests for `/later`, `/backlog`, and `/boss`.
- Handler-level tests for `/focus`, `/crisis`, `/today` focus hint, and next-focus-after-done messages.
- Handler/job-level tests for rendered evening summary delivery.
- Handler/job-level tests for rendered morning briefing delivery.
- Handler-level tests for `/plan_tomorrow`.
- Handler-level tests for free-text capture and capture confirmation callbacks with aiogram test doubles.
- Handler-level tests for voice capture skeleton.
- Tests for real STT provider integration after provider choice.
- Tests for real AI Advisor provider integration after provider choice.
- Production migration rehearsal on a copied real DB before owner-approved deployment.
- Tests for promoting Later Inbox items into scheduled tasks.
- Tests for boss alert cleanup when a boss task is marked done.
- ContextValidator tests for sleep, second sleep, protected slots, and Siyam warnings.
- Google sync policy tests by category.
- Google reconciliation tests for imported, skipped, echo, and conflict events.
- Broader alert queue recovery/idempotency tests.
- Prayer time cache tests with mocked Aladhan API.
- Quran progress parse/backward-confirmation/daily-summary tests.
- OwnerOnlyMiddleware tests.
- Scheduler job construction tests.
- Persistent crisis stack recovery tests after user-scoped schema/flow is decided.
