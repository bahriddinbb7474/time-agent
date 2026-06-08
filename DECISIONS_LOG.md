# Decisions Log

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
- Many Russian user-facing strings in source files appear mojibake-encoded, which is a product-readiness risk.
