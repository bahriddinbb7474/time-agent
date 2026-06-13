# Database Migrations

## Current State

Alembic is not configured and is not listed in `requirements.txt`.
Do not add Alembic until a separate dependency decision is made.

Startup runs `src/app/db/migration_runner.py` from `src/app/main.py`.
`Base.metadata.create_all()` is no longer used in the production startup path.

Current schema-changing migrations:

- `versions/20260101_0000_baseline_pre_stage14.sql` creates the pre-Stage 14 schema for clean installs.
- `versions/20260609_1300_add_daily_plan_lifecycle.sql` adds nullable `tasks.completed_at` and creates `daily_plans`.

Codex verified these migrations only on temporary SQLite DBs. They have not been run against production `data/app.db`.

## Local Migration Approach

Future project-local migrations should live in `migrations/versions/`.

`src/app/db/migration_runner.py` owns the `schema_migrations` table and records applied migration IDs. Migration SQL files must not create or insert into `schema_migrations` themselves.

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

Each migration should be:

- one small schema change;
- idempotent where SQLite allows it;
- reviewed before running;
- tested on a copied or temporary SQLite DB before production;
- never run against `data/app.db` during Codex verification unless explicitly requested.

## Naming

Use timestamped file names:

```text
YYYYMMDD_HHMM_short_description.sql
```

Example:

```text
20260608_1200_add_task_user_id.sql
```

## Safe Workflow

1. Back up the target SQLite DB.
2. Apply the migration to a copied DB first.
3. Verify the app starts and core queries work.
4. Apply to production only with explicit owner approval.
5. Let the runner insert the migration version into `schema_migrations` in the same controlled transaction.

## Rules

- Do not run schema-changing migrations against production `data/app.db` without an explicit owner request.
- Back up the production SQLite DB before any real migration.
- Test every migration on a copied or temporary SQLite DB before production.
- Future migrations must not be mixed with unrelated code changes.
