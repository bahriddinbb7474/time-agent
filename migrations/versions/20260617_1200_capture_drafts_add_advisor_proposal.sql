-- Stage 19.7-D: add advisor_proposal_json to capture_drafts
-- Stores only safe structured proposal fields (no prompt, no response, no user text)

ALTER TABLE capture_drafts ADD COLUMN advisor_proposal_json TEXT NULL;
