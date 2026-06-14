CREATE TABLE IF NOT EXISTS api_usage (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         DATETIME NOT NULL,
    usage_date         DATE NOT NULL,
    provider           VARCHAR(32) NOT NULL,
    service_type       VARCHAR(16) NOT NULL,
    model              VARCHAR(128) NOT NULL,
    request_count      INTEGER NOT NULL DEFAULT 1,
    audio_seconds      REAL NOT NULL DEFAULT 0.0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    status             VARCHAR(24) NOT NULL DEFAULT 'success'
);

CREATE INDEX IF NOT EXISTS ix_api_usage_date_service
ON api_usage (usage_date, service_type);

CREATE INDEX IF NOT EXISTS ix_api_usage_created_at
ON api_usage (created_at);
