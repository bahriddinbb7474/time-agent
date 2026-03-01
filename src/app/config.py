from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_telegram_id: int | None
    tz: str


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Put it into .env")

    raw_id = os.getenv("ALLOWED_TELEGRAM_ID", "").strip()
    allowed_id = int(raw_id) if raw_id else None

    tz = os.getenv("TZ", "Asia/Tashkent").strip() or "Asia/Tashkent"

    return Config(
        bot_token=token,
        allowed_telegram_id=allowed_id,
        tz=tz,
    )
