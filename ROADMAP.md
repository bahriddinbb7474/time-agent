# Roadmap to Time-Agent v1

> Summary only.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## Current Status

- Stages through 20.6: CLOSED / production PASS.
- Stage 20.7-A: local PASS (`a9e703e`).
- Current target: Stage 20-FINAL.
- Production HEAD: `8973f80`.

## Route

1. Stage 20-FINAL — time groups, planned completion accounting, confirmed text/voice facts, no-data semantics, and the 24-hour mirror.
2. Stage 21 — small Goal Engine across daily, monthly, six-month, and yearly horizons.
3. Stage 22 — minimal Ideas + Relationships modules.
4. Stage 23 — production hardening, deploy, observation, and final acceptance.

## Boundaries

- Google Calendar and integrations are not current scope.
- Free check-in text/voice requires an LLM proposal and owner confirmation before a fact write.
- No answer remains no-data; the bot does not invent activity or waste.
- Advanced statistics/forecasting, web UI, complex CRM/ERP, and exact time tracking are post-v1.

## Executor Rule

Before each stage, the owner chooses Codex or Claude Code.

- Codex follows root `AGENTS.md`.
- Claude Code follows root `CLAUDE.md`.
