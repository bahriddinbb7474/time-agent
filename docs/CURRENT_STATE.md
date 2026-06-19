# Current State — Time-Agent

> Last updated: Stage 20.1 CLOSED (2026-06-19).
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`

## Stage 20.1 — Daily Control Foundation: CLOSED

Stage 20.1-A/B/C is complete and production-verified.

### What was built

**Stage 20.1-A — core schema**
- Production foundation schema added for Daily Control:
  - `daily_schedules`
  - `time_blocks`
  - `activity_entries`
  - `checkins`
- Production baseline commit: `ee8d92f`.

**Stage 20.1-B — domain services**
- Daily Control domain service layer added for schedule/block/check-in storage and retrieval.
- Production baseline commit: `6190b79`.

**Stage 20.1-C — interval accounting**
- Interval/accounting logic added to support activity tracking and rollup behavior.
- Production baseline commit: `014d54f`.

### Production verify result

- Production HEAD: `014d54f`
- DB integrity: `ok`
- `daily_schedules_exists=1`
- `time_blocks_exists=1`
- `activity_entries_exists=1`
- `checkins_exists=1`
- Container logs: no traceback / error / exception during verify

### Stage verdict

- Stage 20.1: **CLOSED / PRODUCTION PASS**
- Next stage: **Stage 20.2 — Schedule Proposal Builder**

---

## Stage 19 — LLM Capture Intelligence: CLOSED

Stage 19 is complete. All sub-stages through 19.9 are deployed and verified.

### What was built

**Rules-first capture routing (Stage 19.1–19.3)**
- `CaptureRouterService.classify_text()` assigns `advisor_intent` ("capture" / "help" / "settings" / "unknown") before any LLM call.
- High-confidence captures (task / later / boss from rules) bypass the Advisor entirely.
- Daily target commands are handled by `targets_router` (registered before `capture_router`) and never reach the Advisor.

**AI Advisor pipeline (Stage 19.3–19.7)**
- `AdvisorOrchestrator`: disabled-check → gate-check → provider.advise() → record-usage → validate → result.
- `AdvisorUsageGate`: enforces `LLM_DAILY_REQUEST_LIMIT` and `LLM_DAILY_COST_USD_LIMIT` before any real call.
- `OpenRouterAdvisorProvider`: calls OpenRouter chat/completions API with an injection-safe system prompt. Response is strict JSON.
- `AdvisorProposalValidator`: validates AI proposal against prayer/context rules before presenting to owner.
- `format_advisor_result`: converts orchestration result to presentation DTO with `safe_to_show` flag.

**Telegram wiring (Stage 19.7-D)**
- `_try_advisor_response()` in `capture.py`: checks runtime switch → calls advisor → shows result with `advisor_capture:` buttons.
- `advisor_proposal_json` column added to `capture_drafts` table (migration `20260617_1200_capture_drafts_add_advisor_proposal.sql`).
- Stored proposal contains only 11 safe structured fields — no prompt, raw LLM response, or user text.
- `advisor_capture:` callback handles: confirm_task / confirm_later / confirm_boss / confirm_settings_change (stub) / ask_clarification / cancel.
- settings_change is currently a stub: marks confirmed, shows message, does not mutate daily targets.

**Owner runtime switch (Stage 19.9)**
- `/advisor_status` — shows runtime state, provider config, limits, key presence. No secrets printed.
- `/advisor_on` — enables Advisor runtime. Blocked if provider disabled, key missing, or limits unsafe.
- `/advisor_off` — disables Advisor runtime immediately.
- `AdvisorRuntimeService`: process-local switch. Default OFF on every restart.
- Runtime state is a shared singleton — the same instance is read by `_try_advisor_response` and the advisor commands.

### Privacy / Safety invariants

- `api_usage` table stores only: `provider`, `service_type`, `model`, `input_tokens`, `output_tokens`, `estimated_cost_usd`, `status`. No prompt, response, transcript, or user text.
- `advisor_proposal_json` in `capture_drafts` stores only: `proposal_type`, `title`, `description`, `category`, `when_text`, `target_name`, `target_value`, `target_unit`, `needs_confirmation`, `needs_clarification`, `user_message`. No raw LLM response, no prompt, no model name, no cost.
- All actionable proposal types (`task`, `later`, `boss`, `settings_change`) are forced `needs_confirmation=True` regardless of LLM output.
- No task, target, or setting is modified without explicit owner confirmation.
- Provider call is bounded to 1 per message. Gate blocks if daily limit reached.
- LLM provider timeout: 15 seconds. On any error, falls through to rules path.

### Environment configuration (production)

```
ADVISOR_PROVIDER=openrouter      # or "disabled" to fully bypass
OPENROUTER_API_KEY=<secret>      # never printed in logs or status
OPENROUTER_ADVISOR_MODEL=openai/gpt-4o-mini   # default
LLM_DAILY_REQUEST_LIMIT=10       # hard gate; 0 = unlimited (unsafe)
LLM_DAILY_COST_USD_LIMIT=0.05    # hard gate; 0.0 = unlimited (unsafe)
```

### Owner commands

| Command | Effect |
|---|---|
| `/advisor_status` | Show runtime state, provider config, limits. Safe: no secrets. |
| `/advisor_on` | Enable Advisor (blocked if config unsafe). |
| `/advisor_off` | Disable Advisor immediately. |

### Current production state

- **Advisor runtime: OFF** (default after restart).
- Provider: `openrouter` (configured, key present).
- Limits: request limit 10 / cost limit $0.05 / day.
- Production is safe: ordinary capture works via rules path. Advisor inactive until owner sends `/advisor_on`.

### Capture flow summary (current)

```
text message
  ↓ CaptureRouterService.classify_text()
    advisor_intent = "capture"/"help"/"settings"/"unknown"
  ↓ expire_old_pending_drafts()
  ↓ if pending draft exists → show confirmation (rules path)
  ↓ _try_advisor_response()
    ├─ runtime OFF or config not ready → return False (fall through)
    ├─ advisor_needed() False (high-confidence capture) → return False
    └─ runtime ON + advisor_needed() True
        → orchestrator.run() → provider.advise() → validate → present
        → if safe_to_show: show advisor proposal with advisor_capture: buttons
        → else: return False (fall through)
  ↓ [fall through] create_pending_draft() + show capture buttons (capture: namespace)
```

---

## Next: Stage 20.2 — Schedule Proposal Builder

Stage 20.1 foundation is closed. The next planned step is Stage 20.2.

---

## Regression coverage (Stage 19 close)

| Test file | Tests | Status |
|---|---|---|
| `test_advisor_owner_switch.py` | 12 | PASS |
| `test_advisor_capture_service.py` | 30 | PASS |
| `test_openrouter_advisor.py` | 22 | PASS |
| `test_advisor_orchestrator.py` | 18 | PASS |
| `test_advisor_presentation_service.py` | 23 | PASS |
| `test_prod_openrouter_smoke_script.py` | 8 | PASS |
| `test_capture_drafts.py` | 28 | PASS |
| `test_daily_targets_handlers.py` | 32 | PASS |
| **Total** | **173** | **PASS** |
