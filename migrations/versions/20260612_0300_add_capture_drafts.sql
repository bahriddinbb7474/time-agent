CREATE TABLE IF NOT EXISTS capture_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id BIGINT NOT NULL,
    telegram_user_id BIGINT NOT NULL,
    source VARCHAR(16) NOT NULL DEFAULT 'text',
    raw_text TEXT NOT NULL,
    transcript TEXT NULL,
    suggested_type VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
);

CREATE INDEX IF NOT EXISTS ix_capture_drafts_user_status_created
ON capture_drafts (telegram_chat_id, telegram_user_id, status, created_at);

CREATE INDEX IF NOT EXISTS ix_capture_drafts_status_expires
ON capture_drafts (status, expires_at);
