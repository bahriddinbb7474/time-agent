-- Stage 18.6-C0: add input_tokens and output_tokens to api_usage.
-- STT rows default to 0. Future LLM rows will set these fields in Stage 19.
ALTER TABLE api_usage ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE api_usage ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0;
