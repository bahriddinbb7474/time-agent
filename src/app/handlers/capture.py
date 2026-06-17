from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.core.time import now_tz
from app.services.capture_confirmation_service import (
    ADVISOR_CAPTURE_CALLBACK_PREFIX,
    CAPTURE_ACTION_BOSS,
    CAPTURE_ACTION_CANCEL,
    CAPTURE_ACTION_EXPIRED_CANCEL,
    CAPTURE_ACTION_EXPIRED_LATER,
    CAPTURE_ACTION_LATER,
    CAPTURE_ACTION_TASK,
    CAPTURE_CALLBACK_PREFIX,
    build_advisor_button_specs,
    build_capture_button_specs,
    build_capture_confirmation_text,
    build_expired_capture_button_specs,
    build_expired_capture_text,
)
from app.services.capture_action_service import CaptureActionService
from app.services.capture_draft_service import (
    CAPTURE_DRAFT_SOURCE_VOICE,
    CaptureDraftService,
)
from app.services.capture_router_service import (
    CAPTURE_KIND_IGNORE,
    CaptureRouterService,
)
from app.services.advisor_capture_service import (
    advisor_needed,
    build_safe_advisor_proposal_json,
    run_advisor_for_draft,
)
from app.services.advisor_presentation_service import format_advisor_result
from app.services.api_limit_service import ApiLimitService
from app.services.api_usage_service import ApiUsageService
from app.services.stt_provider import DisabledSTTProvider, OpenRouterSTTProvider, get_stt_provider
from app.services.voice_capture_safety import (
    downloaded_voice_temp_path,
    validate_voice_safety,
)


log = logging.getLogger(__name__)

router = Router()

# Process-level lock serialises the preflight check and the provider call so
# that two concurrent voice messages cannot both pass the last available limit
# slot.  Valid for single-instance deployment only.  Multi-instance requires
# a distributed lock or a DB-level reservation pattern.
_STT_LOCK: asyncio.Lock = asyncio.Lock()


def build_capture_confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button.text,
                    callback_data=button.callback_data,
                )
            ]
            for button in build_capture_button_specs()
        ]
    )


def build_expired_capture_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button.text,
                    callback_data=button.callback_data,
                )
            ]
            for button in build_expired_capture_button_specs()
        ]
    )


def _build_advisor_keyboard(presentation) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.callback_data)]
            for b in build_advisor_button_specs(presentation)
        ]
    )


async def _try_advisor_response(
    message: Message,
    session: AsyncSession,
    draft,
    draft_service: CaptureDraftService,
    settings,
    *,
    source: str = "text",
    transcript: str | None = None,
) -> bool:
    """Try to show an advisor response. Returns True if handled, False to fall through."""
    if not advisor_needed(draft):
        return False

    try:
        orch_result = await run_advisor_for_draft(
            draft, session=session, settings=settings,
        )
        presentation = format_advisor_result(orch_result)
    except Exception:
        log.warning("Advisor failed, falling through to rules", exc_info=True)
        return False

    if not presentation.safe_to_show:
        return False

    if presentation.requires_confirmation:
        proposal_json = None
        if orch_result.validation_result is not None:
            proposal_json = build_safe_advisor_proposal_json(
                orch_result.validation_result.safe_proposal,
            )

        await draft_service.create_pending_draft(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            draft=draft,
            source=source,
            transcript=transcript,
            advisor_proposal_json=proposal_json,
        )
        await message.answer(
            presentation.text,
            reply_markup=_build_advisor_keyboard(presentation),
        )
        return True

    await message.answer(presentation.text)
    return True


async def _record_stt_usage_best_effort(
    session,
    result,
    voice_duration: int,
    settings,
    status: str,
) -> None:
    audio_seconds = (
        result.usage.audio_seconds
        if result is not None
        and result.usage is not None
        and result.usage.audio_seconds is not None
        else float(voice_duration)
    )
    cost = (
        result.usage.estimated_cost_usd
        if result is not None
        and result.usage is not None
        and result.usage.estimated_cost_usd is not None
        else 0.0
    )
    try:
        async with session.begin_nested():
            await ApiUsageService(session).record_stt(
                provider="openrouter",
                model=settings.openrouter_stt_model,
                audio_seconds=audio_seconds,
                estimated_cost_usd=cost,
                status=status,
            )
    except Exception:
        log.warning("Failed to record STT usage", exc_info=True)


@router.message(F.voice)
async def capture_voice_message(
    message: Message,
    session: AsyncSession,
    settings=None,
    stt_provider=None,
):
    settings = settings or load_config()
    provider = stt_provider or get_stt_provider(settings)

    if isinstance(provider, DisabledSTTProvider):
        result = await provider.transcribe_audio(Path(""))
        await message.answer(result.user_message)
        return

    if message.voice is None or message.chat is None or message.from_user is None:
        await message.answer("Голос не найден.")
        return

    safety = validate_voice_safety(
        message.voice,
        max_duration_sec=settings.stt_max_duration_sec,
        max_file_mb=settings.stt_max_file_mb,
    )
    if not safety.allowed:
        await message.answer(safety.user_message or "Голос нельзя обработать.")
        return

    voice_duration = message.voice.duration
    result = None

    # Lock covers preflight + provider call + usage recording.
    # Ensures two concurrent requests cannot both pass the last available slot.
    async with _STT_LOCK:
        # ── Preflight hard-limit check ───────────────────────────────────────
        try:
            decision = await ApiLimitService(session, settings).check_stt(
                planned_seconds=float(voice_duration),
                usage_date=now_tz().date(),
            )
        except Exception:
            # fail-open per canonical TZ §18.6-D: DB error must not block owner
            log.warning("STT limit check failed; allowing request (fail-open)")
            decision = None

        if decision is not None and not decision.allowed:
            try:
                async with session.begin_nested():
                    await ApiUsageService(session).record_limit_exceeded(
                        provider="openrouter",
                        service_type="stt",
                        model=settings.openrouter_stt_model,
                    )
            except Exception:
                log.warning("Failed to record STT limit_exceeded usage", exc_info=True)
            await message.answer(
                "Лимит распознавания на сегодня достигнут.\nНапиши сообщение текстом."
            )
            return

        # ── STT provider call ────────────────────────────────────────────────
        stt_request_started = False
        try:
            async with downloaded_voice_temp_path(message) as audio_path:
                stt_request_started = True
                result = await provider.transcribe_audio(audio_path)
        except Exception:
            if stt_request_started and isinstance(provider, OpenRouterSTTProvider):
                await _record_stt_usage_best_effort(
                    session, result, voice_duration, settings, "error"
                )
            log.exception("Voice processing failed")
            await message.answer("Не удалось обработать голос. Отправь текстом.")
            return

        if isinstance(provider, OpenRouterSTTProvider) and result.request_made:
            status = "success" if result.enabled else "error"
            await _record_stt_usage_best_effort(
                session, result, voice_duration, settings, status
            )

    # Lock released; result is always set here (all error paths return above)
    if not result.enabled or not result.text:
        await message.answer(result.user_message)
        return

    draft = CaptureRouterService().classify_text(result.text)
    if draft.kind == CAPTURE_KIND_IGNORE:
        await message.answer(result.user_message)
        return

    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )

    expired_record = await draft_service.get_latest_expired_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if expired_record is not None:
        await message.answer(
            build_expired_capture_text(draft_service.to_capture_draft(expired_record)),
            reply_markup=build_expired_capture_keyboard(),
        )
        return

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if pending_record is not None:
        await message.answer(
            build_capture_confirmation_text(
                draft_service.to_capture_draft(pending_record)
            ),
            reply_markup=build_capture_confirmation_keyboard(),
        )
        return

    handled = await _try_advisor_response(
        message, session, draft, draft_service, settings,
        source=CAPTURE_DRAFT_SOURCE_VOICE,
        transcript=result.text,
    )
    if handled:
        return

    await draft_service.create_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        draft=draft,
        source=CAPTURE_DRAFT_SOURCE_VOICE,
        transcript=result.text,
    )

    await message.answer(
        build_capture_confirmation_text(draft),
        reply_markup=build_capture_confirmation_keyboard(),
    )


@router.message(F.text & ~F.text.startswith("/"))
async def capture_text_message(
    message: Message, session: AsyncSession, settings=None,
):
    if message.text is None or message.chat is None or message.from_user is None:
        return

    settings = settings or load_config()
    draft = CaptureRouterService().classify_text(message.text)
    if draft.kind == CAPTURE_KIND_IGNORE:
        return

    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )

    expired_record = await draft_service.get_latest_expired_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if expired_record is not None:
        await message.answer(
            build_expired_capture_text(draft_service.to_capture_draft(expired_record)),
            reply_markup=build_expired_capture_keyboard(),
        )
        return

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    if pending_record is not None:
        await message.answer(
            build_capture_confirmation_text(
                draft_service.to_capture_draft(pending_record)
            ),
            reply_markup=build_capture_confirmation_keyboard(),
        )
        return

    handled = await _try_advisor_response(
        message, session, draft, draft_service, settings,
    )
    if handled:
        return

    await draft_service.create_pending_draft(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        draft=draft,
    )

    await message.answer(
        build_capture_confirmation_text(draft),
        reply_markup=build_capture_confirmation_keyboard(),
    )


@router.callback_query(F.data.startswith(f"{CAPTURE_CALLBACK_PREFIX}:"))
async def capture_confirmation_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    action = (callback.data or "").removeprefix(f"{CAPTURE_CALLBACK_PREFIX}:")
    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    service = CaptureActionService(
        session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    if action in {CAPTURE_ACTION_EXPIRED_LATER, CAPTURE_ACTION_EXPIRED_CANCEL}:
        expired_record = await draft_service.get_latest_expired_draft(
            chat_id=callback.message.chat.id,
            user_id=callback.from_user.id,
        )
        if expired_record is None:
            await _finalize_capture_ui(callback)
            await callback.answer("Черновик не найден.", show_alert=True)
            return

        if action == CAPTURE_ACTION_EXPIRED_LATER:
            task = await service.create_later_from_text(expired_record.raw_text)
            await draft_service.mark_confirmed(expired_record)
            await _finalize_capture_ui(callback)
            await callback.message.answer(f"На потом: #{task.id}")
            await callback.answer()
            return

        await draft_service.mark_cancelled(expired_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    if action == CAPTURE_ACTION_CANCEL:
        if pending_record is not None:
            await draft_service.mark_cancelled(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    if action not in {CAPTURE_ACTION_LATER, CAPTURE_ACTION_BOSS, CAPTURE_ACTION_TASK}:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    if pending_record is None:
        await _finalize_capture_ui(callback)
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    draft = draft_service.to_capture_draft(pending_record)

    if action == CAPTURE_ACTION_LATER:
        task = await service.create_later_from_text(draft.text)
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"На потом: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_BOSS:
        task = await service.create_boss_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"Boss задача: #{task.id}")
        await callback.answer()
        return

    if action == CAPTURE_ACTION_TASK:
        result = await service.create_task_from_text(
            draft.text,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
        return


async def _finalize_capture_ui(callback: CallbackQuery) -> None:
    if callback.message is None:
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        return


# ── Advisor capture confirmation callback ────────────────────────────────────


def _parse_advisor_proposal_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        import json
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("proposal_type"):
            return data
        return None
    except (json.JSONDecodeError, TypeError):
        return None


@router.callback_query(F.data.startswith(f"{ADVISOR_CAPTURE_CALLBACK_PREFIX}:"))
async def advisor_capture_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    scheduler: AsyncIOScheduler,
):
    if callback.message is None or callback.from_user is None:
        await callback.answer("Нет активного действия.", show_alert=False)
        return

    action = (callback.data or "").removeprefix(f"{ADVISOR_CAPTURE_CALLBACK_PREFIX}:")
    draft_service = CaptureDraftService(session)
    await draft_service.expire_old_pending_drafts(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    pending_record = await draft_service.get_latest_pending_draft(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
    )

    if action == "cancel":
        if pending_record is not None:
            await draft_service.mark_cancelled(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Отменено.")
        await callback.answer()
        return

    if action == "ask_clarification":
        await _finalize_capture_ui(callback)
        await callback.message.answer("Уточните запрос текстом.")
        await callback.answer()
        return

    if pending_record is None:
        await _finalize_capture_ui(callback)
        await callback.answer("Черновик не найден.", show_alert=True)
        return

    proposal = _parse_advisor_proposal_json(
        getattr(pending_record, "advisor_proposal_json", None)
    )
    if proposal is None:
        await draft_service.mark_cancelled(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer("Предложение AI устарело. Попробуйте снова.")
        await callback.answer()
        return

    service = CaptureActionService(
        session,
        scheduler=scheduler,
        bot=callback.bot,
    )

    if action == "confirm_later":
        title = proposal.get("title") or pending_record.raw_text
        task = await service.create_later_from_text(title)
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"На потом: #{task.id}")
        await callback.answer()
        return

    if action == "confirm_boss":
        title = proposal.get("title") or pending_record.raw_text
        task = await service.create_boss_from_text(
            title,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(f"Boss задача: #{task.id}")
        await callback.answer()
        return

    if action == "confirm_task":
        title = proposal.get("title") or pending_record.raw_text
        result = await service.create_task_from_text(
            title,
            user_id=callback.from_user.id,
        )
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(result.user_message)
        await callback.answer()
        return

    if action == "confirm_settings_change":
        await draft_service.mark_confirmed(pending_record)
        await _finalize_capture_ui(callback)
        await callback.message.answer(
            "Предложение принято. Изменение целей будет подключено на следующем этапе."
        )
        await callback.answer()
        return

    await callback.answer("Неизвестное действие.", show_alert=True)
