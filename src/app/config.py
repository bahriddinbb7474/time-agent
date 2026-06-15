from dataclasses import dataclass
import math
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    allowed_telegram_id: int | None
    tz: str
    enable_debug_commands: bool
    stt_provider: str
    advisor_provider: str
    llm_daily_limit: int
    stt_max_duration_sec: int
    stt_max_file_mb: int
    openrouter_api_key: str
    openrouter_stt_model: str
    openrouter_stt_language: str
    # Stage 18.6-D: hard limits (0 = unlimited per canonical TZ)
    stt_daily_request_limit: int
    stt_daily_seconds_limit: int
    llm_daily_request_limit: int
    llm_daily_cost_usd_limit: float


def _parse_limit_int(env_name: str, raw: str) -> int:
    stripped = (raw or "").strip()
    try:
        v = int(stripped)
    except (ValueError, TypeError):
        raise ValueError(
            f"{env_name}: expected non-negative integer, got {stripped!r}"
        )
    if v < 0:
        raise ValueError(f"{env_name}: must be >= 0, got {v}")
    return v


def _parse_limit_float(env_name: str, raw: str) -> float:
    stripped = (raw or "").strip()
    try:
        v = float(stripped)
    except (ValueError, TypeError):
        raise ValueError(
            f"{env_name}: expected non-negative float, got {stripped!r}"
        )
    if not math.isfinite(v):
        raise ValueError(f"{env_name}: must be finite, got {stripped!r}")
    if v < 0:
        raise ValueError(f"{env_name}: must be >= 0, got {v}")
    return v


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Put it into .env")

    raw_id = os.getenv("ALLOWED_TELEGRAM_ID", "").strip()
    allowed_id = int(raw_id) if raw_id else None

    tz = os.getenv("TZ", "Asia/Tashkent").strip() or "Asia/Tashkent"
    enable_debug_commands = (
        os.getenv("ENABLE_DEBUG_COMMANDS", "false").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    stt_provider = os.getenv("STT_PROVIDER", "disabled").strip().lower() or "disabled"
    advisor_provider = (
        os.getenv("ADVISOR_PROVIDER", "disabled").strip().lower() or "disabled"
    )
    llm_daily_limit = int(os.getenv("LLM_DAILY_LIMIT", "0").strip() or "0")
    stt_max_duration_sec = int(os.getenv("STT_MAX_DURATION_SEC", "60").strip() or "60")
    stt_max_file_mb = int(os.getenv("STT_MAX_FILE_MB", "10").strip() or "10")
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openrouter_stt_model = (
        os.getenv("OPENROUTER_STT_MODEL", "").strip() or "openai/whisper-large-v3"
    )
    openrouter_stt_language = os.getenv("OPENROUTER_STT_LANGUAGE", "").strip()

    stt_daily_request_limit = _parse_limit_int(
        "STT_DAILY_REQUEST_LIMIT",
        os.getenv("STT_DAILY_REQUEST_LIMIT", "0") or "0",
    )
    stt_daily_seconds_limit = _parse_limit_int(
        "STT_DAILY_SECONDS_LIMIT",
        os.getenv("STT_DAILY_SECONDS_LIMIT", "0") or "0",
    )
    llm_daily_request_limit = _parse_limit_int(
        "LLM_DAILY_REQUEST_LIMIT",
        os.getenv("LLM_DAILY_REQUEST_LIMIT", "0") or "0",
    )
    llm_daily_cost_usd_limit = _parse_limit_float(
        "LLM_DAILY_COST_USD_LIMIT",
        os.getenv("LLM_DAILY_COST_USD_LIMIT", "0.0") or "0.0",
    )

    return Config(
        bot_token=token,
        allowed_telegram_id=allowed_id,
        tz=tz,
        enable_debug_commands=enable_debug_commands,
        stt_provider=stt_provider,
        advisor_provider=advisor_provider,
        llm_daily_limit=llm_daily_limit,
        stt_max_duration_sec=stt_max_duration_sec,
        stt_max_file_mb=stt_max_file_mb,
        openrouter_api_key=openrouter_api_key,
        openrouter_stt_model=openrouter_stt_model,
        openrouter_stt_language=openrouter_stt_language,
        stt_daily_request_limit=stt_daily_request_limit,
        stt_daily_seconds_limit=stt_daily_seconds_limit,
        llm_daily_request_limit=llm_daily_request_limit,
        llm_daily_cost_usd_limit=llm_daily_cost_usd_limit,
    )
