# Roadmap to Time-Agent v1

> Summary only.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## Current Status

- Stage 18.6-P: CLOSED / PRODUCTION PASS.
- Production code HEAD at smoke: `fd23d87`.
- Repository HEAD before v8.1 docs update: `41fd89c`.
- Current next stage: Stage 18.6-C0.
- Stage 18.7 is not started.

## Route

- 18.6-C0: token fields.
- 18.6-C: `/usage`.
- 18.6-D: hard limits.
- PRE-18.7 / PRE-19: audits and fixes.
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
