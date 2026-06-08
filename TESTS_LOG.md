# Tests Log

## Existing Tests Found

- No pytest/unittest suite found.
- `src/app/db/test_oauth_state_repo.py` is a manual async smoke test using an isolated temporary SQLite DB.
- Handler names `test_brief_cmd` and `test_evening_cmd` are Telegram command handlers, not tests.

## Tests Run

Safe manual DB smoke command:

```powershell
$env:PYTHONPATH="src;.venv\Lib\site-packages"; & "C:\Users\USER\AppData\Local\Programs\Python\Python311\python.exe" src/app/db/test_oauth_state_repo.py
```

This command must use a temporary SQLite DB and must not touch `data/app.db`.

## Migration Verification

No migration was run. The migration foundation is documentation-only and must not write to `data/app.db`.

## Debug Command Safety

`/test_brief`, `/test_evening`, and `/gcal_debug` are gated by `ENABLE_DEBUG_COMMANDS=false` by default.

## Missing Critical Tests

- Import smoke test for all app modules.
- Config loading tests for missing/valid env.
- DB init and seed tests.
- Task create/edit/delete service tests.
- ContextValidator tests for sleep, second sleep, prayer, Dhuhr dead zone, protected slots, and Siyam warnings.
- Google sync policy tests by category.
- Google reconciliation tests for imported, skipped, echo, and conflict events.
- Alert queue recovery/idempotency tests.
- Prayer time cache tests with mocked Aladhan API.
- Quran progress parse/backward-confirmation/daily-summary tests.
- OwnerOnlyMiddleware tests.
- Scheduler job construction tests.
