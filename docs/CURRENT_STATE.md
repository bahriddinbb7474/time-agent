# Current State — Time-Agent

> Last updated: Stage 20-FINAL text-first hotfix deployed and smoked (2026-06-22).
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`

## Authoritative Current Direction

Time-Agent is a Telegram-first goal-driven life dispatcher / external memory:

`life goals → daily plan → dynamic day support → urgent capture → fact accounting → 24-hour summary → tomorrow plan`

The owner wants an approximate, honest view of where 24 valuable hours went and a
small actionable improvement for tomorrow. Google Calendar and external integrations
are removed from current scope; remaining calendar tables/repositories are legacy cleanup only.

### Git and rollout state

- Repository HEAD before this documentation update: `148304c`.
- Production HEAD: `148304c`.
- Stage 20-FINAL hotfix `148304c` (`fix: make check-ins text-first`) is pushed, pulled on VPS and deployed with `docker compose up -d --build`.
- Telegram smoke PASS:
  - `/checkin_test` shows the text/voice-first message without the old 5 buttons.
  - Voice/text with AI OFF fails closed and saves nothing.
  - `не помню` stays rules-first and returns `Записано: нет данных.`
- Stage 20.7-A unknown policy hardening is local PASS and creates no fake activity.
- Rejected Stage 20.7 B/C/D/E waste-button commits are not in `main`.

### Important current gaps

- `Сделал` marks a task done but does not create an actual fact interval.
- Unknown/no-answer/no-data semantics are not yet integrated into the final accounting report.
- Existing evening summary is not the final 24-hour mirror.
- Categories are coarse strings, not the shared life/time-group dictionary.
- Next implementation step: gap-driven planner.

## Final v1 Roadmap

1. **Stage 20-FINAL — 24-hour mirror MVP**
   - shared time groups;
   - planned completion → idempotent fact;
   - check-in text/voice → LLM proposal → owner confirmation → fact;
   - no answer = no-data; no fake activity and no auto-waste;
   - evening 24-hour group summary and tomorrow advice;
   - privacy/cost regression and production smoke.
2. **Stage 21 — Goal Engine**
   - reuse Daily Targets;
   - add small daily/monthly/six-month/year goal management;
   - map every goal to a time group and surface it in planning/review.
3. **Stage 22 — Ideas + Relationships**
   - minimal Idea Vault with status, next step and notes;
   - extend RelativesContactRule into simple family/close/friends/work reminders.
4. **Stage 23 — Production finish + final acceptance**
   - hardening, backup/restore, scheduler recovery, health, final Telegram/VPS smoke and docs;
   - legacy calendar cleanup only after a safe migration audit.

Advanced statistics/forecasting, web UI, complex CRM/ERP and exact time tracking are post-v1.

## Stage 20.6 — Свободный текст и голос: CLOSED

Stage 20.6 is complete and production-smoked.

### What was built

**Stage 20.6 — simplified free-text and voice path**
- Architecture stays simplified: no large local NLP subsystem is introduced.
- Known typed replies remain rules-first.
- Ambiguous typed text does not create activity without confirmation.
- Voice path adds an STT/voice AI boundary and an LLM interpretation path.
- Voice runtime/provider OFF fails closed safely.
- Any LLM proposal requires explicit owner confirmation before mutation.
- No raw transcript, prompt, or raw LLM response is stored.
- No private transcript or private text is written to INFO logs.
- `не помню` creates no fake activity.
- No auto-waste behavior is introduced.
- Production baseline commits:
  - `e004a79` — free-text boundary
  - `a71a860` — STT boundary
  - `7b7355e` — confirmed LLM proposal
  - `8973f80` — smoke contract

### Production smoke result

- Production HEAD: `8973f80`
- typed `Другое` + owner text writes owner-provided activity fact
- activity fact stored with `source=checkin`
- `owner_confirmed=1`
- `waste_marked_by_owner=0`
- voice while AI/LLM OFF returns a safe disabled message
- no mutation before confirmation
- unknown / no-memory creates no fake activity
- no auto-waste
- no OpenRouter / no LLM call during disabled smoke
- logs clean: no traceback / error / exception / openrouter / transcript

### Stage 20.6 boundaries

- Known typed replies stay rules-first
- Voice runtime/provider OFF fails closed safely
- No OpenRouter calls during disabled smoke
- Advisor runtime remains default OFF
- No OpenRouter calls happen unless owner enables Advisor manually

### Stage verdict

- Stage 20.6: **CLOSED / PRODUCTION PASS**
- Superseded next-stage note: active roadmap now continues with **Stage 20-FINAL**.

## Stage 20.5 — Rules-first ответы: CLOSED

Stage 20.5 is complete and production-smoked.

### What was built

**Stage 20.5 — deterministic rules-first response path**
- Rules-first response classifier added.
- RU/UZ/EN deterministic intents added for check-in text answers.
- Text replies are routed to active check-ins only when confidence is high.
- Normal capture flow remains unchanged when there is no active check-in.
- Button and text replies share one safe response path.
- Supported outcomes: `aligned`, `started`, `defer`, `unknown`, `other_text`, `cancel`, and fallback.
- `не помню` creates no fake activity.
- `Другое` stores only the owner-provided fact, validated to 1-256 chars.
- No auto-waste behavior is introduced.
- No OpenRouter or LLM usage in this stage.
- No private user text is written to INFO logs.
- Production baseline commits:
  - `6c04fbd` — classifier
  - `52686e5` — application service
  - `ae91021` — text routing
  - `c5ee5dd` — safe other flow
  - `1e88964` — smoke contract

### Production smoke result

- Production HEAD: `1e88964`
- `/checkin_test` sends a real check-in message
- text `всё по плану` -> `answered/aligned`
- text `не помню` -> `answered/unknown`, no fake activity
- text `начал` -> `answered/started`
- text `позже` / defer -> `deferred`
- `Другое` + owner text -> owner-provided activity fact
- `activities=1` only for owner-provided `other_text`
- no auto-waste
- no OpenRouter / no LLM
- logs clean: no traceback / error / exception

### Stage 20.5 boundaries

- No OpenRouter calls
- No LLM usage
- Advisor runtime remains default OFF
- No OpenRouter calls happen unless owner enables Advisor manually

### Stage verdict

- Stage 20.5: **CLOSED / PRODUCTION PASS**
- Next stage: **Stage 20.6 — Свободный текст и голос**

## Stage 20.4 — Check-in Scheduler / periodic plan control: CLOSED

Stage 20.4 is complete and production-verified.

### What was built

**Stage 20.4 — policy, scheduler, Telegram, accounting**
- Durable 60/120-minute check-in policy foundation added.
- Restart-safe scheduler recovery added for check-in jobs.
- Owner-only Telegram check-in callbacks added.
- Accounting integration added for `aligned` / `unknown` / `deferred`.
- No fake activity is created.
- No auto-waste behavior is introduced.
- No OpenRouter or LLM usage in this stage.
- Production baseline commits:
  - `18ad27e` — check-in policy foundation
  - `c8a5ccf` — scheduler recovery
  - `fb27cd9` — Telegram callbacks
  - `814d837` — accounting integration
  - `b0b54ff` — smoke contract
  - `08798c4` — migration registry/context fix
  - `79192d2` — owner `/checkin_test` smoke command

### Production verify result

- Production HEAD: `79192d2`
- DB integrity: `ok`
- `checkins` table exists
- checkins created: `24`
- pending/deferred records present
- protected sleep/prayer slots are deferred
- scheduler contains `run_checkin_job` jobs
- `/health` ok
- `/schedule_tomorrow` still shows confirmed schedule
- `/checkin_test` sends a real check-in message
- Callback results verified:
  - `✅ Всё по плану` → `answered/aligned`
  - `❓ Не помню` → `answered/unknown`, no fake activity
  - `⏸ Отложить` → `deferred`
- Container logs: no traceback / error / exception during verify

### Stage 20.4 boundaries

- No OpenRouter calls
- No LLM usage
- Advisor runtime remains default OFF

### Stage verdict

- Stage 20.4: **CLOSED / PRODUCTION PASS**
- Next stage: **Stage 20.5 — Rules-first ответы**

---

## Stage 20.3 — Confirmation UX / Schedule Proposal Review: CLOSED

Stage 20.3 and its production hotfixes are complete and production-smoked.

### What was built

**Stage 20.3 — confirmation service and review command**
- Owner-only `/schedule_tomorrow` command added for schedule proposal review.
- Durable confirmation service added for proposal lifecycle.
- Production baseline commits:
  - `f35f4da` — confirmation service
  - `5790e1e` — review command

**Stage 20.3 — callbacks and edit foundation**
- Confirm / decline / rebuild callbacks added.
- Safe edit foundation/stub added; edit path remains non-destructive.
- Production baseline commits:
  - `d4e0d4f` — callbacks
  - `83d7ad2` — edit foundation
  - `31b30d5` — smoke contract

**Production hotfixes**
- Protected sleep/prayer overlap handling fixed.
- Handler path fails closed on builder validation errors.
- Confirmed schedule is shown directly before rebuild instead of silently replacing active state.
- Hotfix commits:
  - `946c913` — protected overlap fix
  - `d115feb` — fail-closed handler
  - `ff9b879` — show confirmed schedule before rebuilding

### Production smoke result

- Production HEAD: `ff9b879`
- `/schedule_tomorrow` shows confirmed schedule
- Repeated command shows existing confirmed plan, not a new draft
- Rebuild from confirmed schedule does not replace the active confirmed schedule
- Edit path shows a safe stub
- Container logs: no traceback / error / exception during smoke

### Stage 20.3 boundaries

- No scheduler wiring yet
- No morning briefing wiring yet
- No OpenRouter calls
- Advisor runtime remains default OFF

### Stage verdict

- Stage 20.3: **CLOSED / PRODUCTION PASS**
- Next stage: **Stage 20.4 — Check-in Scheduler / periodic plan control**

---

## Stage 20.2 — Schedule Proposal Builder: CLOSED

Stage 20.2-A/B/C/D is complete and production-deployed by owner.

### What was built

**Stage 20.2-A — proposal builder skeleton**
- Deterministic schedule proposal builder added.
- Proposal draft behavior is idempotent.
- No auto-confirm path.
- Production baseline commit: `bc1b9cf`.

**Stage 20.2-B — protected slots**
- Prayer and sleep windows are enforced as protected slots.
- Overload is routed into `unscheduled_items` instead of forcing invalid placement.
- Builder keeps a 10% buffer target.
- Production baseline commit: `2852ac0`.

**Stage 20.2-C — input integration**
- Proposal input collector added.
- Uses cached prayer times, sleep routines, and timed tasks.
- No network dependency and no OpenRouter usage.
- Production baseline commit: `4c269e1`.

**Stage 20.2-D — formatter**
- Privacy-aware schedule proposal formatter added.
- Summary output is capped at 15 lines.
- No Telegram handler wiring or scheduler wiring yet.
- Production baseline commit: `e398861`.

### Production state

- Production HEAD: `e398861`
- Stage verdict: **CLOSED / PRODUCTION PASS**
- Next stage: **Stage 20.3 — Confirmation UX / schedule proposal review**

### Stage 20 safety boundaries

- Stage 20.1 foundation remains the base data layer:
  - `daily_schedules`
  - `time_blocks`
  - `activity_entries`
  - `checkins`
- Stage 20.2 remains deterministic and local-only:
  - no network calls
  - no OpenRouter calls
  - no auto-confirm
  - no Telegram/scheduler wiring yet

---

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
- No OpenRouter calls happen unless owner enables Advisor manually.

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

## Next: gap-driven planner

Stage 20-FINAL text-first hotfix `148304c` is deployed and Telegram-smoked in production.
Continue with the gap-driven planner only. Google Calendar and external integrations remain
out of scope and must not be restored.

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
