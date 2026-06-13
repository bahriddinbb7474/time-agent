-- This migration was verified only on temp DBs and was never applied to production.
-- Version tracking is owned by the migration runner, not by migration SQL files.

ALTER TABLE tasks ADD COLUMN completed_at DATETIME NULL;

CREATE TABLE IF NOT EXISTS daily_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date DATE NOT NULL,
    text TEXT NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'telegram_manual',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_daily_plans_plan_date UNIQUE (plan_date)
);

CREATE INDEX IF NOT EXISTS ix_daily_plans_plan_date
    ON daily_plans (plan_date);
