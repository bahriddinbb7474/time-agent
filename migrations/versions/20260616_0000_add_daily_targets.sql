-- Stage 18.7.1: daily target definitions and per-day progress tracking.
-- Two tables, no runtime behaviour changes.

CREATE TABLE daily_target_definitions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    category      TEXT    NOT NULL DEFAULT 'general',
    unit          TEXT    NOT NULL,
    target_value  REAL    NOT NULL,
    target_mode   TEXT    NOT NULL DEFAULT 'minimum',
    priority      INTEGER NOT NULL DEFAULT 100,
    weekdays_mask INTEGER NOT NULL DEFAULT 127,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);

CREATE TABLE daily_target_progress (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id              INTEGER NOT NULL REFERENCES daily_target_definitions(id) ON DELETE CASCADE,
    usage_date             TEXT    NOT NULL,
    planned_value_snapshot REAL    NOT NULL,
    actual_value           REAL    NOT NULL DEFAULT 0.0,
    status                 TEXT    NOT NULL DEFAULT 'in_progress',
    note                   TEXT,
    updated_at             TEXT    NOT NULL,
    UNIQUE (target_id, usage_date)
);

CREATE INDEX ix_daily_target_definitions_active      ON daily_target_definitions (active);
CREATE INDEX ix_daily_target_progress_usage_date     ON daily_target_progress (usage_date);
CREATE INDEX ix_daily_target_progress_target_id      ON daily_target_progress (target_id);
