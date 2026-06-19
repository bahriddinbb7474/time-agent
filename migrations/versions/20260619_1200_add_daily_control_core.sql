-- Stage 20.1-A: Daily Control schedule, fact, and check-in foundation.
-- Runtime behavior is intentionally added in later stages.

CREATE TABLE IF NOT EXISTS daily_schedules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    usage_date   TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'draft',
    version      INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    confirmed_at TEXT,
    CONSTRAINT uq_daily_schedules_user_date UNIQUE (user_id, usage_date)
);

CREATE TABLE IF NOT EXISTS time_blocks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id  INTEGER NOT NULL REFERENCES daily_schedules(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL,
    start_at     TEXT    NOT NULL,
    end_at       TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    block_type   TEXT    NOT NULL,
    flexibility  TEXT    NOT NULL,
    source_type  TEXT    NOT NULL,
    source_id    INTEGER,
    status       TEXT    NOT NULL DEFAULT 'planned',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    CONSTRAINT ck_time_blocks_valid_interval CHECK (end_at > start_at)
);

CREATE TABLE IF NOT EXISTS activity_entries (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               INTEGER NOT NULL,
    usage_date            TEXT    NOT NULL,
    start_at              TEXT    NOT NULL,
    end_at                TEXT    NOT NULL,
    title                 TEXT    NOT NULL,
    category              TEXT    NOT NULL,
    source                TEXT    NOT NULL,
    confidence            REAL,
    owner_confirmed       INTEGER NOT NULL DEFAULT 0,
    waste_marked_by_owner INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL,
    CONSTRAINT ck_activity_entries_valid_interval CHECK (end_at > start_at),
    CONSTRAINT ck_activity_entries_confidence_range
        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_activity_entries_waste_owner_confirmed
        CHECK (waste_marked_by_owner = 0 OR owner_confirmed = 1)
);

CREATE TABLE IF NOT EXISTS checkins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    window_start  TEXT    NOT NULL,
    window_end    TEXT    NOT NULL,
    prompted_at   TEXT    NOT NULL,
    answered_at   TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending',
    response_mode TEXT,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    CONSTRAINT uq_checkins_user_window UNIQUE (user_id, window_start, window_end),
    CONSTRAINT ck_checkins_valid_window CHECK (window_end > window_start)
);

CREATE INDEX IF NOT EXISTS ix_daily_schedules_user_date
    ON daily_schedules (user_id, usage_date);
CREATE INDEX IF NOT EXISTS ix_daily_schedules_status
    ON daily_schedules (status);
CREATE INDEX IF NOT EXISTS ix_time_blocks_schedule_start
    ON time_blocks (schedule_id, start_at);
CREATE INDEX IF NOT EXISTS ix_time_blocks_user_start
    ON time_blocks (user_id, start_at);
CREATE INDEX IF NOT EXISTS ix_activity_entries_user_date
    ON activity_entries (user_id, usage_date);
CREATE INDEX IF NOT EXISTS ix_activity_entries_user_start
    ON activity_entries (user_id, start_at);
CREATE INDEX IF NOT EXISTS ix_checkins_user_window
    ON checkins (user_id, window_start);
CREATE INDEX IF NOT EXISTS ix_checkins_user_status
    ON checkins (user_id, status);
