# Decisions Log

> Historical or summary document.
> Canonical plan: `docs/TZ_TIME_AGENT_FINAL_v8_1.md`.

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

## Visible Architecture Decisions

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
