# Database Migrations

## Current State

Alembic is not configured and is not listed in `requirements.txt`.
Do not add Alembic until a separate dependency decision is made.

Startup still calls `Base.metadata.create_all()` in `src/app/main.py`.
Keep that behavior for now, but do not rely on it for production schema evolution.

Current schema-changing migration:

- `versions/20260609_1300_add_daily_plan_lifecycle.sql` adds nullable `tasks.completed_at`, creates `daily_plans`, and records its version in `schema_migrations`.

Codex verified this migration only on a temporary SQLite DB. It has not been run against production `data/app.db`.

## Local Migration Approach

Future project-local migrations should live in `migrations/versions/`.

Use a DB table named `schema_migrations` to track applied migration IDs:

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
5. Insert the migration version into `schema_migrations` in the same controlled step.

## Rules

- Do not run schema-changing migrations against production `data/app.db` without an explicit owner request.
- Back up the production SQLite DB before any real migration.
- Test every migration on a copied or temporary SQLite DB before production.
- Future migrations must not be mixed with unrelated code changes.
