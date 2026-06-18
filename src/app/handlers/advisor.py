from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import load_config
from app.services.advisor_runtime_service import AdvisorRuntimeStatus, advisor_runtime


router = Router()


def _is_owner(message: Message, settings) -> bool:
    owner_id = getattr(settings, "allowed_telegram_id", None)
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    return owner_id is not None and user_id == owner_id


def _status_text(status: AdvisorRuntimeStatus) -> str:
    state = "SAFE" if status.safe else "UNSAFE"
    return "\n".join(
        [
            f"Advisor runtime: {'enabled' if status.enabled else 'disabled'}",
            f"Provider configured: {'yes' if status.provider_configured else 'no'}",
            f"API key present: {'yes' if status.key_present else 'no'}",
            f"LLM_DAILY_REQUEST_LIMIT: {status.request_limit}",
            f"LLM_DAILY_COST_USD_LIMIT: {status.cost_limit_usd:g}",
            f"State: {state}",
            f"Ready to enable: {'yes' if status.configuration_ready else 'no'}",
        ]
    )


def _blocked_text(status: AdvisorRuntimeStatus) -> str:
    if "provider_disabled" in status.blockers:
        return "Advisor не включён: provider disabled in env."
    if "provider_unsupported" in status.blockers:
        return "Advisor не включён: provider в env не поддерживается."
    if "key_missing" in status.blockers:
        return "Advisor не включён: OPENROUTER_API_KEY отсутствует."
    if "request_limit_unsafe" in status.blockers:
        return "Advisor не включён: LLM_DAILY_REQUEST_LIMIT должен быть больше 0."
    return "Advisor не включён: LLM_DAILY_COST_USD_LIMIT должен быть больше 0."


@router.message(Command("advisor_status"))
async def advisor_status_cmd(message: Message, settings=None) -> None:
    settings = settings or load_config()
    if not _is_owner(message, settings):
        return
    await message.answer(_status_text(advisor_runtime.status(settings)))


@router.message(Command("advisor_on"))
async def advisor_on_cmd(message: Message, settings=None) -> None:
    settings = settings or load_config()
    if not _is_owner(message, settings):
        return

    status = advisor_runtime.enable(settings)
    if not status.enabled:
        await message.answer(_blocked_text(status))
        return
    await message.answer("Advisor runtime: enabled.")


@router.message(Command("advisor_off"))
async def advisor_off_cmd(message: Message, settings=None) -> None:
    settings = settings or load_config()
    if not _is_owner(message, settings):
        return
    advisor_runtime.disable()
    await message.answer("Advisor runtime: disabled.")
