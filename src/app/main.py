import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.config import load_config
from app.logging_setup import setup_logging
from app.security import OwnerOnlyMiddleware

router = Router()
log = logging.getLogger("time-agent")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("ok")


@router.message(F.text)
async def any_text(message: Message) -> None:
    await message.answer("ok")


async def main() -> None:
    setup_logging()
    cfg = load_config()

    log.info("Starting bot… TZ=%s allowed_id=%s", cfg.tz, cfg.allowed_telegram_id)

    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher()

    # Security: пускаем только владельца
    dp.message.middleware(OwnerOnlyMiddleware(cfg.allowed_telegram_id))
    # (позже добавим middleware и на callback/inline и т.д., если понадобится)

    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
