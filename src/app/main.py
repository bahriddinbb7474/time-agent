import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from app.config import load_config
from app.logging_setup import setup_logging
from app.security import OwnerOnlyMiddleware

from app.handlers.common import router as common_router
from app.handlers.rules import router as rules_router
from app.handlers.add import router as add_router
from app.handlers.today import router as today_router
from app.handlers.task_lifecycle import router as task_lifecycle_router
from app.handlers.quran import router as quran_router
from app.handlers.targets import router as targets_router
from app.handlers.capture import router as capture_router
from app.handlers.usage import router as usage_router

from app.db.database import get_sessionmaker
from app.db.migration_runner import run_migrations
from app.db.seed import seed_if_empty
from app.db.middleware import DbSessionMiddleware
from app.scheduler.scheduler import build_scheduler, recover_alerts
from app.scheduler.jobs import morning_briefing

log = logging.getLogger("time-agent")

DB_PATH = Path("data") / "app.db"


async def init_db() -> None:
    """
    Production DB initialization.

    Schema is managed by project migrations. Seed runs only after migrations.
    """
    result = run_migrations(DB_PATH)
    log.info(
        "DB migrations checked: applied=%s skipped=%s",
        result.applied,
        result.skipped,
    )

    Session = get_sessionmaker()
    async with Session() as session:
        await seed_if_empty(session)
        log.info("DB seed checked (seed_if_empty).")


async def main() -> None:
    setup_logging()
    cfg = load_config()

    log.info("Starting bot... TZ=%s allowed_id=%s", cfg.tz, cfg.allowed_telegram_id)

    await init_db()

    bot = Bot(token=cfg.bot_token)
    scheduler = build_scheduler(bot, db_path=DB_PATH)
    scheduler.start()
    log.info("Scheduler started")

    try:
        await morning_briefing(bot, scheduler)
        log.info("Startup morning briefing completed")
    except Exception:
        log.exception("Startup morning briefing failed")

    dp = Dispatcher()
    dp["scheduler"] = scheduler

    Session = get_sessionmaker()

    try:
        async with Session() as session:
            await recover_alerts(
                scheduler=scheduler,
                session=session,
                bot=bot,
            )
        log.info("Persistent alerts recovery completed")
    except Exception:
        log.exception("Alert recovery failed — startup continues without full recovery")

    dp.message.middleware(OwnerOnlyMiddleware(cfg.allowed_telegram_id))
    dp.message.middleware(DbSessionMiddleware())

    dp.callback_query.middleware(OwnerOnlyMiddleware(cfg.allowed_telegram_id))
    dp.callback_query.middleware(DbSessionMiddleware())

    dp.include_router(common_router)
    dp.include_router(rules_router)
    dp.include_router(add_router)
    dp.include_router(task_lifecycle_router)
    dp.include_router(today_router)
    dp.include_router(quran_router)
    dp.include_router(targets_router)
    dp.include_router(capture_router)
    dp.include_router(usage_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
