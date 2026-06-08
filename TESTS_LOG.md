# Tests Log

## Existing Tests Found

- No pytest/unittest suite found.
- `src/app/db/test_oauth_state_repo.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_task_status.py` is a manual async smoke test using an isolated temporary SQLite DB.
- `src/app/db/test_later_inbox.py` is a manual async smoke test using an isolated temporary SQLite DB.
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

Python note: the documented Python path requires existing `.venv\Lib\site-packages` on `PYTHONPATH` for project dependencies in this environment. `.venv\Scripts\python.exe` exists but its launcher is broken.

## Migration Verification

No migration was run. The migration foundation is documentation-only and must not write to `data/app.db`.

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
- Task create/edit/delete service tests beyond the current manual status smoke.
- Handler-level tests for `/done` and `task_done:<id>`.
- Handler-level tests for `/later`, `/backlog`, and `/boss`.
- Tests for promoting Later Inbox items into scheduled tasks.
- Tests for boss alert cleanup when a boss task is marked done.
- ContextValidator tests for sleep, second sleep, prayer, Dhuhr dead zone, protected slots, and Siyam warnings.
- Google sync policy tests by category.
- Google reconciliation tests for imported, skipped, echo, and conflict events.
- Alert queue recovery/idempotency tests.
- Prayer time cache tests with mocked Aladhan API.
- Quran progress parse/backward-confirmation/daily-summary tests.
- OwnerOnlyMiddleware tests.
- Scheduler job construction tests.
