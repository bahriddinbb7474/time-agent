-- Stage 20.4-A: restart-safe association of check-ins with confirmed schedules.

ALTER TABLE checkins ADD COLUMN schedule_id INTEGER;
ALTER TABLE checkins ADD COLUMN schedule_version INTEGER;
ALTER TABLE checkins ADD COLUMN usage_date TEXT;

CREATE INDEX IF NOT EXISTS ix_checkins_schedule_version
    ON checkins (schedule_id, schedule_version);
CREATE INDEX IF NOT EXISTS ix_checkins_user_date
    ON checkins (user_id, usage_date);
