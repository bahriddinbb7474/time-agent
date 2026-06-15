# Project Map

> Summary only.
> Canonical project plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## Purpose

Time-Agent is a Telegram bot for personal mental-load dispatching with context-aware scheduling: protected slots, sleep windows, prayer windows, Siyam/health context, reminders, capture drafts, and planning.

## Current Route

- 18.6-C0: token fields.
- 18.6-C: `/usage`.
- 18.6-D: hard limits.
- PRE-18.7 / PRE-19: audits and fixes.
- 18.7: Daily Targets MVP; does not depend on LLM and depends on completed audits/migration foundation.
- 19: LLM Capture Intelligence.
- 20: Daily Control 24/7; depends on Stage 19.
- 21: Task Lifecycle.
- 22: Production hardening + main DoD.
- 23: Idea Vault.
- 24: Statistics & Forecasting; depends on sufficient data quality.

## Repository Structure

```text
time-agent/
├─ src/app/
│  ├─ main.py                         # Bot startup, DB init, scheduler, routers
│  ├─ config.py                       # TELEGRAM_BOT_TOKEN, ALLOWED_TELEGRAM_ID, TZ
│  ├─ security.py                     # OwnerOnlyMiddleware
│  ├─ core/time.py                    # Asia/Tashkent time helpers
│  ├─ handlers/                       # Telegram command and callback handlers
│  │  ├─ common.py                    # /start, test brief/evening, prayer callbacks
│  │  ├─ add.py                       # /add parser and confirmation buttons
│  │  ├─ task_lifecycle.py            # /edit and /delete
│  │  ├─ today.py                     # /today, /siyam_on, /siyam_off
│  │  ├─ rules.py                     # /rules
│  │  ├─ gcal.py                      # /gcal_* commands and conflict callbacks
│  │  └─ quran.py                     # /quran and /quran_status
│  ├─ services/                       # Business logic
│  │  ├─ task_service.py              # Local task CRUD facade and context status
│  │  ├─ task_sync_service.py         # Local task plus Google sync orchestration
│  │  ├─ task_sync_policy_service.py  # Category-based sync policy
│  │  ├─ context_validator.py         # Read-only scheduling validation
│  │  ├─ prayer_times_service.py      # Aladhan Tashkent Hanafi prayer cache
│  │  ├─ daily_context_service.py     # Siyam/health daily policy
│  │  ├─ quran_service.py             # Quran progress and daily goal logic
│  │  ├─ family_contact_service.py    # Family reminder candidates
│  │  ├─ boss_priority_service.py     # Boss/critical alert decisions
│  │  └─ google_*_service.py          # Calendar service and reconciliation
│  ├─ scheduler/
│  │  ├─ scheduler.py                 # APScheduler setup and alert recovery
│  │  └─ jobs.py                      # Briefings, prayer cache, alert firing
│  ├─ db/
│  │  ├─ models.py                    # SQLAlchemy ORM models
│  │  ├─ crud.py                      # Core CRUD helpers
│  │  ├─ *_repo.py                    # OAuth and external link repositories
│  │  ├─ database.py                  # SQLite async engine/sessionmaker
│  │  ├─ middleware.py                # DB session middleware for aiogram
│  │  └─ seed.py                      # Default rules and routines
│  └─ integrations/google/
│     ├─ auth.py                      # OAuth credentials, token, scopes
│     ├─ calendar_client.py           # Google Calendar API calls
│     ├─ oauth_server.py              # Local OAuth callback server
│     ├─ dto.py                       # Google DTOs
│     └─ mappers.py                   # Integration mapping helpers
├─ data/                              # Local SQLite database path
├─ logs/                              # Runtime logs
├─ secrets/                           # Local secrets folder
├─ Dockerfile                         # Python 3.11 slim container
├─ docker-compose.yml                 # Bot service, logs/data volumes, OAuth port
├─ requirements.txt                   # Python dependencies
├─ AGENTS.md                          # Local Codex/project instructions
├─ STAGE_SNAPSHOT.md                  # Development workflow snapshot
├─ FAST_BUG_SCAN.md                   # Bug scan workflow doc
├─ BUG_FIX_TEMPLATE.md                # Bug fix task template
└─ *.md                               # Project info and status documents
```

## Main Runtime Flow

1. `app.main` loads config and logging.
2. SQLite schema is updated through the project migration runner.
3. Seed data is inserted if missing.
4. APScheduler starts recurring jobs and recovers persistent alerts.
5. Aiogram registers owner-only middleware, DB middleware, and routers.
6. Bot starts polling Telegram.

## Data Model Areas

- `Rule`: protected slots.
- `Task`: local tasks with category, status, planned time, and context status.
- `TaskExternalLink`: Google Calendar sync state.
- `OAuthState`: Google OAuth PKCE state.
- `UserRoutine`: sleep and second-sleep routines.
- `PrayerTime`: cached daily prayer times.
- `AlertQueue`: persistent reminders.
- `QuranProgressEntry`: Quran progress log.
- `RelativesContactRule`: family contact cadence.
- `DailyHealthContext`: Siyam/health policy.
- `CrisisStack` and `CrisisStackTask`: early crisis/focus stack foundation.

## Important Operational Files

- `requirements.txt`: pinned runtime dependencies.
- `Dockerfile`: runs `python -m app.main` with `PYTHONPATH=/app/src`.
- `docker-compose.yml`: mounts logs and app data, exposes port `8085` for OAuth callback.
- `.env.example`: placeholder-only runtime configuration.
