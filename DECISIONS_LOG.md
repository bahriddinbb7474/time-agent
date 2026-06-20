# Decisions Log

> Historical or summary document.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

## 2026-06-21 — Final v1 roadmap correction

This decision supersedes the 2026-06-15 Stage 20–24 ordering where they conflict.

1. Time-Agent is a Telegram-first goal-driven life dispatcher / external memory.
2. Active route: Stage 20-FINAL → Stage 21 Goal Engine → Stage 22 Ideas + Relationships → Stage 23 Production finish.
3. Google Calendar/integrations are removed from current scope; remaining artifacts are legacy cleanup only.
4. Free check-in text/voice requires LLM interpretation, structured proposal and owner confirmation before fact mutation.
5. No answer remains no-data; the bot does not invent activity or waste.
6. `Впустую` comes only from owner text/voice plus confirmed proposal; no primary waste button.
7. Advanced statistics/forecasting, web UI, complex CRM/ERP and exact time tracking are post-v1.

## 2026-06-15 — Time-Agent plan v8.1 adopted

1. Daily Targets включён как Stage 18.7.
2. Daily Control включён как Stage 20.
3. Task Lifecycle сдвинут на Stage 21.
4. Production hardening и основной DoD — Stage 22.
5. Idea Vault — Stage 23.
6. Statistics & Forecasting — Stage 24.
7. Stage 23-24 post-final и не двигают DoD.
8. Исполнитель выбирается владельцем перед этапом: Codex follows `AGENTS.md`; Claude Code follows `CLAUDE.md`.
9. Check-in rules-first.
10. Сон protected.
11. `Впустую` только owner-selected.

## Historical architecture snapshot

The entries below describe earlier repository history. They are not authoritative
where they conflict with the 2026-06-21 correction or the canonical plan.

- Telegram-first interface: the application is an aiogram Telegram bot, started from `app.main`.
- Owner-only access: `OwnerOnlyMiddleware` allows only `ALLOWED_TELEGRAM_ID`; if it is missing, access fails closed.
- Timezone baseline: application time is fixed to `Asia/Tashkent` in `app.core.time.APP_TZ`; config also defaults `TZ` to `Asia/Tashkent`.
- Local persistence: SQLite via SQLAlchemy async engine at `./data/app.db`.
- Dev-safe schema creation: startup calls `Base.metadata.create_all()` and then seeds default rules/routines.
- Scheduler-first reminders: APScheduler runs morning briefing, evening summary, prayer cache, family daily check, and persistent alert recovery.
- Persistent alert queue: reminders are stored in `alert_queue` and restored after restart.
- Prayer rule: prayer times are fetched from Aladhan for Tashkent, Uzbekistan, with method `3` and school `1` (Hanafi/Mithlayn).
- Prayer protection: context validation blocks or warns around prayer windows; Dhuhr has a specific 13:00-13:20 dead zone shifted to 13:25.
- ContextValidator is read-only by design: it returns `ValidationResult` and does not create/update tasks or write DB state.
- Google Calendar policy is category based: `work` syncs to Google; `family`, `health`, `prayer`, `personal`, and `other` stay local or restricted local.
- Google Calendar read-first/reconcile path exists: `/gcal_today`, `/gcal_pull`, debug, OAuth, and conflict surfacing are implemented.
- Google writes are local-task driven: synced events include private metadata with `source=telegram_time_agent` and `local_task_id`.
- Family reminders are controlled candidates: current family daily job reads rules and logs due candidates, without auto-creating tasks.
- Siyam/health foundation is explicit-or-heuristic: explicit `/siyam_on` and `/siyam_off` override Monday/Thursday heuristic.
- Quran tracking is local: `/quran` records progress, validates backward page movement, and evening summary can create follow-up alerts.

## Notes

- Root `.env.example` is empty, while code expects several environment variables.
- UTF-8 scan found only one real runtime mojibake string in `src/app/main.py`; Telegram user-facing Russian strings are readable when files are read as UTF-8.
- Mojibake marker strings in `src/app/scheduler/jobs.py` are intentional fallback detection and must not be removed.
