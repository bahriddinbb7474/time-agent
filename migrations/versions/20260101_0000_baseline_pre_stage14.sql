CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(128) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    days_of_week VARCHAR(32) NOT NULL DEFAULT '*',
    policy VARCHAR(32) NOT NULL DEFAULT 'never_move'
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title VARCHAR(256) NOT NULL,
    planned_at DATETIME NULL,
    duration_min INTEGER NOT NULL DEFAULT 30,
    status VARCHAR(16) NOT NULL DEFAULT 'todo',
    category VARCHAR(32) NOT NULL DEFAULT 'personal',
    context_status VARCHAR(32) NOT NULL DEFAULT 'normal',
    created_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tasks_context_status
    ON tasks (context_status);

CREATE TABLE IF NOT EXISTS crisis_stacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_crisis_stacks_user_status
    ON crisis_stacks (user_id, status);

CREATE TABLE IF NOT EXISTS crisis_stack_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stack_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    priority_position INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_crisis_stack_tasks_stack_task UNIQUE (stack_id, task_id),
    CONSTRAINT uq_crisis_stack_tasks_stack_priority UNIQUE (stack_id, priority_position),
    FOREIGN KEY(stack_id) REFERENCES crisis_stacks(id) ON DELETE CASCADE,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_crisis_stack_tasks_stack_priority
    ON crisis_stack_tasks (stack_id, priority_position);

CREATE TABLE IF NOT EXISTS task_external_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    provider VARCHAR(64) NOT NULL,
    external_id VARCHAR(256) NULL,
    external_calendar_id VARCHAR(256) NULL,
    sync_status VARCHAR(32) NOT NULL DEFAULT 'sync_pending',
    skip_reason VARCHAR(64) NULL,
    last_error TEXT NULL,
    last_synced_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_task_external_links_task_provider UNIQUE (task_id, provider),
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_task_external_links_sync_status
    ON task_external_links (sync_status);

CREATE INDEX IF NOT EXISTS ix_task_external_links_external_id
    ON task_external_links (external_id);

CREATE TABLE IF NOT EXISTS oauth_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id BIGINT NOT NULL,
    state VARCHAR(256) NOT NULL UNIQUE,
    code_verifier VARCHAR(512) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    is_used BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_oauth_states_user_id
    ON oauth_states (user_id);

CREATE INDEX IF NOT EXISTS ix_oauth_states_state
    ON oauth_states (state);

CREATE INDEX IF NOT EXISTS ix_oauth_states_user_state
    ON oauth_states (user_id, state);

CREATE TABLE IF NOT EXISTS user_routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode VARCHAR(16) NOT NULL,
    sleep_start TIME NOT NULL,
    sleep_end TIME NOT NULL,
    second_sleep_start TIME NULL,
    second_sleep_end TIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_user_routines_mode UNIQUE (mode)
);

CREATE INDEX IF NOT EXISTS ix_user_routines_mode
    ON user_routines (mode);

CREATE TABLE IF NOT EXISTS prayer_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    fajr TIME NOT NULL,
    dhuhr TIME NOT NULL,
    asr TIME NOT NULL,
    maghrib TIME NOT NULL,
    isha TIME NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_prayer_times_date UNIQUE (date)
);

CREATE INDEX IF NOT EXISTS ix_prayer_times_date
    ON prayer_times (date);

CREATE TABLE IF NOT EXISTS alert_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type VARCHAR(32) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(64) NULL,
    scheduled_for DATETIME NOT NULL,
    repeat_interval_min INTEGER NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    payload_json TEXT NULL,
    last_fired_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_alert_queue_status
    ON alert_queue (status);

CREATE INDEX IF NOT EXISTS ix_alert_queue_scheduled_for
    ON alert_queue (scheduled_for);

CREATE INDEX IF NOT EXISTS ix_alert_queue_priority
    ON alert_queue (priority);

CREATE INDEX IF NOT EXISTS ix_alert_queue_type_status
    ON alert_queue (alert_type, status);

CREATE INDEX IF NOT EXISTS ix_alert_queue_entity
    ON alert_queue (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS quran_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surah VARCHAR(128) NOT NULL,
    ayah INTEGER NOT NULL,
    page INTEGER NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_quran_progress_created_at
    ON quran_progress (created_at);

CREATE INDEX IF NOT EXISTS ix_quran_progress_page
    ON quran_progress (page);

CREATE TABLE IF NOT EXISTS relatives_contact_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(1) NOT NULL,
    min_contact_frequency INTEGER NOT NULL,
    contact_type VARCHAR(16) NOT NULL,
    last_contact_at DATETIME NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_relatives_contact_rules_category
    ON relatives_contact_rules (category);

CREATE INDEX IF NOT EXISTS ix_relatives_contact_rules_contact_type
    ON relatives_contact_rules (contact_type);

CREATE TABLE IF NOT EXISTS daily_health_contexts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL,
    is_siyam_day BOOLEAN NOT NULL DEFAULT 0,
    siyam_state_source VARCHAR(16) NOT NULL DEFAULT 'heuristic',
    hydration_daylight_suppressed BOOLEAN NOT NULL DEFAULT 0,
    low_energy_mode BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_daily_health_contexts_date UNIQUE (date)
);

CREATE INDEX IF NOT EXISTS ix_daily_health_contexts_date
    ON daily_health_contexts (date);
