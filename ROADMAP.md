# Roadmap to Time-Agent v1

> Summary only.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## Current Status

- 18.6-C0: CLOSED / PRODUCTION PASS.
- 18.6-C: CLOSED / PRODUCTION PASS.
- 18.6-D: CLOSED / PRODUCTION PASS.
- PRE-18.7-A: CLOSED / audit PASS.
- PRE-18.7-B: CLOSED / pushed (`1e81d73`).
- PRE-18.7-C: current — docs cleanup.
- Production HEAD (last deployed): `2c9b47e`.
- Repository HEAD: `1e81d73`.
- Stage 18.7 is not started.

## Route

- 18.6-C0: DONE.
- 18.6-C: DONE.
- 18.6-D: DONE.
- PRE-18.7-A/B/C: DONE / in progress.
- Remaining before 18.7: Telegram nightly backup (HIGH/OPEN), single-instance PID guard decision.
- 18.7: Daily Targets MVP.
- 19: LLM Capture Intelligence.
- 20: Daily Control 24/7.
- 21: Task Lifecycle.
- 22: Production hardening + main DoD.
- 23: Idea Vault.
- 24: Statistics & Forecasting.

## Dependencies

- Daily Targets does not depend on LLM.
- Daily Targets depends on completed audits and migration foundation.
- Daily Control depends on Stage 19.
- Statistics depends on sufficient data quality.
- Stage 23-24 are post-final modules and do not move the main DoD.

## Executor Rule

Before each stage, the owner chooses Codex or Claude Code.

- Codex follows root `AGENTS.md`.
- Claude Code follows root `CLAUDE.md`.
