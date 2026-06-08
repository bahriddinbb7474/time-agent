# Time-Agent

Telegram-first personal mental load dispatcher for tasks, reminders, protected time, prayer-aware scheduling, and Google Calendar coordination.

## Stack

- Python 3.11
- aiogram 3
- SQLAlchemy 2 async
- SQLite with aiosqlite
- APScheduler
- aiohttp
- Google Calendar API client and OAuth
- Docker / Docker Compose

## Main Features

- Owner-only Telegram bot access.
- Local task management through Telegram commands.
- Context-aware scheduling with sleep, second sleep, protected slots, prayer windows, and Siyam warnings.
- Prayer times for Tashkent using Aladhan API with Hanafi school.
- Persistent reminders backed by SQLite `alert_queue`.
- Morning briefing and evening summary jobs.
- Google Calendar connect/read/debug/pull commands.
- Category-based Google sync: work can sync; personal/family/health/prayer stay local or restricted.
- Quran progress tracking and evening follow-up.
- Basic family contact reminder candidates.
- Boss/critical alert foundation.

## Project Layout

See `PROJECT_MAP.md` for the current repository map.

## Configuration

The app loads `.env` via `python-dotenv`.

Required or used variables visible in code:

- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_TELEGRAM_ID`
- `TZ` defaults to `Asia/Tashkent`
- `ENABLE_DEBUG_COMMANDS` defaults to `false`
- `GCAL_CREDENTIALS_PATH`
- `GCAL_TOKEN_PATH`
- `GCAL_OAUTH_REDIRECT_URI`
- `GCAL_SCOPES` defaults to Google Calendar events scope
- `GCAL_OAUTH_BIND_HOST` defaults to `0.0.0.0`
- `GCAL_OAUTH_PORT` defaults to `8085`
- `GCAL_OAUTH_TIMEOUT_SEC` defaults to `300`

See `.env.example` for placeholder values.

## Database Migrations

Runtime still uses SQLAlchemy `create_all()` on startup as a safety net.
Future schema changes should use the project-local approach documented in `migrations/README.md`.
No schema-changing migration exists yet.

## Local Run

Based on `Dockerfile`, the Python entrypoint is:

```bash
python -m app.main
```

For local non-Docker execution, set `PYTHONPATH` so `app` resolves from `src`.

## Docker

The Docker image runs:

```bash
python -m app.main
```

Docker Compose defines one `bot` service, mounts `./logs`, persists `/app/data` in a volume, mounts `C:/time-agent-secrets` read-only to `/run/secrets`, exposes `8085:8085`, and restarts always.

Typical command supported by existing files:

```bash
docker compose up --build
```

## Docker / Env / Secrets Audit

Safe now:

- Container runs as non-root `appuser`.
- `TZ` defaults to `Asia/Tashkent`; Docker installs `tzdata`.
- SQLite persists under `/app/data`, backed by the `app_data` volume.
- Logs mount to `./logs`; file logging is opt-in with `LOG_TO_FILE=1`.
- Google OAuth credentials are expected as a read-only mounted JSON file.
- Google token path is configurable and should point into persisted `/app/data`.
- Debug/test commands are disabled by default with `ENABLE_DEBUG_COMMANDS=false`.

Not ready yet:

- No Docker healthcheck/heartbeat is configured.
- No documented backup/restore routine for SQLite DB or Google token.
- OAuth redirect URI must be validated for the target VPS domain/port.
- Secrets path `C:/time-agent-secrets` is Windows-host specific and must be adapted for VPS.

## Telegram Commands Visible in Code

- `/start`
- `/health`
- `/rules`
- `/today`
- `/add`
- `/edit`
- `/delete`
- `/siyam_on`
- `/siyam_off`
- `/prayer_today`
- `/quran`
- `/quran_status`
- `/gcal_test`
- `/gcal_connect`
- `/gcal_today`
- `/gcal_debug`
- `/gcal_pull`
- `/test_brief`
- `/test_evening`

Debug/test commands `/test_brief`, `/test_evening`, and `/gcal_debug` only run when `ENABLE_DEBUG_COMMANDS=true`.

`/health` returns a short owner-only runtime check: process alive, timezone, debug flag, DB read status, and scheduler job count.

## Testing

No full automated test suite was found. See `TESTS_LOG.md`.
