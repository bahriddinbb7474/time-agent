CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

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

INSERT OR IGNORE INTO schema_migrations (version, applied_at)
VALUES ('20260609_1300_add_daily_plan_lifecycle', datetime('now'));
