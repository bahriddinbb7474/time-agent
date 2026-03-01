import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = logging.getLogger("time-agent.security")


class OwnerOnlyMiddleware(BaseMiddleware):
    """
    Пропускает апдейты только от владельца (ALLOWED_TELEGRAM_ID).
    Если allowed_id = None, то НИКОГО не пускаем (fail-closed).
    """

    def __init__(self, allowed_id: Optional[int]):
        self.allowed_id = allowed_id
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Пытаемся вытащить from_user безопасно
        from_user = getattr(event, "from_user", None)
        user_id = getattr(from_user, "id", None)

        # Fail-closed: если allowed_id не задан — блокируем всё
        if self.allowed_id is None:
            if user_id:
                log.warning(
                    "Blocked update: ALLOWED_TELEGRAM_ID is not set. user_id=%s",
                    user_id,
                )
            return None

        if user_id != self.allowed_id:
            # не отвечаем, просто игнорируем
            if user_id:
                log.warning("Unauthorized access attempt user_id=%s", user_id)
            return None

        return await handler(event, data)
