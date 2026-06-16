# Project Map

> Summary only.
> Canonical project plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## Purpose

Time-Agent is a Telegram bot for personal mental-load dispatching with context-aware scheduling: protected slots, sleep windows, prayer windows, Siyam/health context, reminders, capture drafts, and planning.

## Current Route

- 18.6-C0: DONE / production PASS.
- 18.6-C: DONE / production PASS.
- 18.6-D: DONE / production PASS.
- PRE-18.7-A: DONE / audit PASS.
- PRE-18.7-B: DONE / pushed.
- PRE-18.7-C: current — docs cleanup.
- Remaining before 18.7: Telegram nightly backup (HIGH/OPEN), single-instance PID guard decision.
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
│  │  ├─ capture.py                   # Voice and text capture drafts
│  │  ├─ usage.py                     # /usage API stats command
│  │  └─ quran.py                     # /quran and /quran_status
│  ├─ services/                       # Business logic
│  │  ├─ task_service.py              # Local task CRUD facade and context status
│  │  ├─ context_validator.py         # Read-only scheduling validation
│  │  ├─ prayer_times_service.py      # Aladhan Tashkent Hanafi prayer cache
│  │  ├─ daily_context_service.py     # Siyam/health daily policy
│  │  ├─ quran_service.py             # Quran progress and daily goal logic
│  │  ├─ family_contact_service.py    # Family reminder candidates
│  │  ├─ boss_priority_service.py     # Boss/critical alert decisions
│  │  ├─ api_limit_service.py         # Daily API hard limits (Stage 18.6-D)
│  │  └─ api_usage_service.py         # API usage recording and aggregation
│  ├─ scheduler/
│  │  ├─ scheduler.py                 # APScheduler setup and alert recovery
│  │  └─ jobs.py                      # Briefings, prayer cache, alert firing
│  ├─ db/
│  │  ├─ models.py                    # SQLAlchemy ORM models
│  │  ├─ crud.py                      # Core CRUD helpers
│  │  ├─ *_repo.py                    # Legacy OAuth and external link repositories (GCal removed; tables kept pending final cleanup)
│  │  ├─ database.py                  # SQLite async engine/sessionmaker
│  │  ├─ middleware.py                # DB session middleware for aiogram
│  │  └─ seed.py                      # Default rules and routines
│  └─ integrations/google/
│     └─ (source files removed in Stage 16a; __pycache__ only — final cleanup postponed)
├─ data/                              # Local SQLite database path
├─ logs/                              # Runtime logs
├─ secrets/                           # Local secrets folder
├─ Dockerfile                         # Python 3.11 slim container
├─ docker-compose.yml                 # Bot service, logs/data volumes (no OAuth port)
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
- `TaskExternalLink`: legacy GCal sync state (GCal runtime removed; table kept pending final cleanup stage).
- `OAuthState`: legacy GCal OAuth PKCE state (same — table kept pending final cleanup stage).
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
- `docker-compose.yml`: mounts logs and app data volumes. No OAuth port exposed (GCal runtime removed).
- `.env.example`: placeholder-only runtime configuration.
