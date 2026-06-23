-- Stage 21-A: durable goal foundation.
-- Small owner-scoped goals table, no planner/report integration yet.

CREATE TABLE goals (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                   INTEGER NOT NULL,
    title                     TEXT    NOT NULL,
    horizon                   TEXT    NOT NULL,
    time_group                TEXT    NOT NULL,
    status                    TEXT    NOT NULL DEFAULT 'active',
    target_value              REAL,
    unit                      TEXT,
    target_mode               TEXT,
    preferred_minutes_per_day INTEGER,
    planning_hint             TEXT,
    priority                  INTEGER NOT NULL DEFAULT 100,
    period_start              TEXT,
    period_end                TEXT,
    created_at                TEXT    NOT NULL,
    updated_at                TEXT    NOT NULL
);

CREATE INDEX ix_goals_user_status  ON goals (user_id, status);
CREATE INDEX ix_goals_user_horizon ON goals (user_id, horizon);
CREATE INDEX ix_goals_time_group   ON goals (time_group);
