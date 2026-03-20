import asyncio
import logging

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
from app.handlers.gcal import build_gcal_router
from app.services.google_calendar_service import GoogleCalendarService

from app.db.database import get_engine, get_sessionmaker
from app.db.models import Base
from app.db.seed import seed_if_empty
from app.db.middleware import DbSessionMiddleware
from app.scheduler.scheduler import build_scheduler, recover_alerts
from app.scheduler.jobs import morning_briefing

log = logging.getLogger("time-agent")


async def init_db() -> None:
    """
    Dev-safe DB initialization.

    Р’Р°Р¶РЅРѕ:
    create_all() РІС‹Р·С‹РІР°РµС‚СЃСЏ РІСЃРµРіРґР°, С‡С‚РѕР±С‹ РїСЂРё РёР·РјРµРЅРµРЅРёРё ORM-СЃС…РµРјС‹
    РЅРµРґРѕСЃС‚Р°СЋС‰РёРµ С‚Р°Р±Р»РёС†С‹ СЃРѕР·РґР°РІР°Р»РёСЃСЊ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.
    """
    log.info("Ensuring DB schema via create_all()...")

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("DB schema ensured (create_all).")

    Session = get_sessionmaker()
    async with Session() as session:
        await seed_if_empty(session)
        log.info("DB seed checked (seed_if_empty).")


async def main() -> None:
    setup_logging()
    cfg = load_config()

    log.info("Starting botвЂ¦ TZ=%s allowed_id=%s", cfg.tz, cfg.allowed_telegram_id)

    await init_db()

    bot = Bot(token=cfg.bot_token)
    scheduler = build_scheduler(bot)
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

    def session_factory():
        return Session()

    async def bot_notify_fn(user_id: int, text: str):
        await bot.send_message(chat_id=user_id, text=text)

    gcal_service = GoogleCalendarService(
        session_factory=session_factory,
        bot_notify_fn=bot_notify_fn,
    )

    async with Session() as session:
        await recover_alerts(
            scheduler=scheduler,
            session=session,
            bot=bot,
        )
        log.info("Persistent alerts recovery completed")

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
    dp.include_router(build_gcal_router(gcal_service))

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
