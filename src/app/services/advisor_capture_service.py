"""
Stage 19.7-D — Thin integration layer between capture flow and advisor pipeline.

Pure orchestration: no Telegram types, no session lifecycle management.
No prompt, response, transcript, or user text is stored.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.advisor_orchestrator import AdvisorOrchestrationResult, AdvisorOrchestrator
from app.services.advisor_proposal_validator import validate_advisor_proposal
from app.services.advisor_usage_gate import AdvisorUsageGate
from app.services.ai_advisor_provider import AdvisorProposal, AdvisorRequest, get_ai_advisor_provider
from app.services.capture_router_service import CaptureDraft

log = logging.getLogger("time-agent.advisor.capture")

_ADVISOR_INTENTS = frozenset({"help", "settings", "unknown", "checkin_fact"})
_EXPLICIT_WASTE_PATTERN = re.compile(
    r"(?:\bвпустую\b|\bпотер(?:ял|яла)\s+время\b|"
    r"\bwast(?:e|ed)\s+time\b|\bbekorga\b)",
    re.IGNORECASE,
)

_SETTINGS_GOAL_PATTERN = re.compile(
    r"\b(?:добавь|добавить|установи|измени|поменяй|настрой)\s+цель\s+"
    r"(?P<name>[а-яёa-z][а-яёa-z0-9 _-]*?)\s+(?:на\s+)?"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>[а-яёa-z]+)\b",
    re.IGNORECASE,
)
_SETTINGS_QUANTITY_PATTERN = re.compile(
    r"\bхочу\s+(?P<value>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>[а-яёa-z]+)\s+(?P<name>[а-яёa-z][а-яёa-z0-9 _-]*)$",
    re.IGNORECASE,
)

_SAFE_PROPOSAL_KEYS = (
    "proposal_type",
    "title",
    "description",
    "category",
    "when_text",
    "target_name",
    "target_value",
    "target_unit",
    "needs_confirmation",
    "needs_clarification",
    "user_message",
)


def advisor_needed(draft: CaptureDraft) -> bool:
    return draft.advisor_intent in _ADVISOR_INTENTS or draft.needs_clarification


def build_safe_advisor_proposal_json(
    proposal: AdvisorProposal,
    *,
    checkin_id: int | None = None,
    waste_explicit: bool = False,
) -> str:
    safe = {k: getattr(proposal, k) for k in _SAFE_PROPOSAL_KEYS}
    if checkin_id is not None:
        safe["checkin_id"] = checkin_id
        safe["waste_explicit"] = waste_explicit
    return json.dumps(safe, ensure_ascii=False)


def _settings_fields(text: str) -> tuple[str, str, str] | None:
    match = _SETTINGS_GOAL_PATTERN.search(text) or _SETTINGS_QUANTITY_PATTERN.search(text)
    if match is None:
        return None
    name = match.group("name").strip()
    value = match.group("value").replace(",", ".")
    unit = match.group("unit").strip()
    return name, value, unit


async def _enforce_settings_intent(
    draft: CaptureDraft,
    result: AdvisorOrchestrationResult,
    *,
    now_dt: datetime | None,
) -> AdvisorOrchestrationResult:
    """Never let a rules-classified settings request become a task proposal."""
    if draft.advisor_intent != "settings" or result.validation_result is None:
        return result

    current = result.validation_result.safe_proposal
    if current.proposal_type == "settings_change" and result.validation_result.valid:
        return result

    fields = _settings_fields(draft.text)
    if fields is None:
        safe = AdvisorProposal(
            intent="settings",
            proposal_type="clarification",
            title=None,
            description=None,
            category=None,
            when_text=None,
            target_name=None,
            target_value=None,
            target_unit=None,
            needs_confirmation=False,
            needs_clarification=True,
            user_message="Уточните название цели и новое значение.",
            model=current.model,
            input_tokens=current.input_tokens,
            output_tokens=current.output_tokens,
            estimated_cost_usd=current.estimated_cost_usd,
            error=False,
        )
    else:
        name, value, unit = fields
        safe = AdvisorProposal(
            intent="settings",
            proposal_type="settings_change",
            title=None,
            description=None,
            category=None,
            when_text=None,
            target_name=name,
            target_value=value,
            target_unit=unit,
            needs_confirmation=True,
            needs_clarification=False,
            user_message=f"Предлагаю изменить цель «{name}»: {value} {unit}.",
            model=current.model,
            input_tokens=current.input_tokens,
            output_tokens=current.output_tokens,
            estimated_cost_usd=current.estimated_cost_usd,
            error=False,
        )

    validation = await validate_advisor_proposal(safe, now_dt=now_dt)
    return AdvisorOrchestrationResult(
        used_advisor=result.used_advisor,
        blocked_by_limit=result.blocked_by_limit,
        provider_error=result.provider_error,
        validation_result=validation,
        user_message=validation.user_message,
        reason_code="settings_intent_guard",
    )


async def _enforce_checkin_fact_intent(
    draft: CaptureDraft,
    result: AdvisorOrchestrationResult,
    *,
    now_dt: datetime | None,
) -> AdvisorOrchestrationResult:
    if draft.advisor_intent != "checkin_fact" or result.validation_result is None:
        return result

    current = result.validation_result.safe_proposal
    valid_activity = current.proposal_type == "activity"
    valid_waste = current.category != "waste" or bool(
        _EXPLICIT_WASTE_PATTERN.search(draft.text)
    )
    if valid_activity and valid_waste and result.validation_result.valid:
        return result

    safe = AdvisorProposal(
        intent="checkin_fact",
        proposal_type="clarification",
        title=None,
        description=None,
        category=None,
        when_text=None,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=False,
        needs_clarification=True,
        user_message="Не удалось безопасно разобрать факт. Уточните, что происходило.",
        model=current.model,
        input_tokens=current.input_tokens,
        output_tokens=current.output_tokens,
        estimated_cost_usd=current.estimated_cost_usd,
        error=False,
    )
    validation = await validate_advisor_proposal(safe, now_dt=now_dt)
    return AdvisorOrchestrationResult(
        used_advisor=result.used_advisor,
        blocked_by_limit=result.blocked_by_limit,
        provider_error=result.provider_error,
        validation_result=validation,
        user_message=validation.user_message,
        reason_code="checkin_fact_guard",
    )


async def run_advisor_for_draft(
    draft: CaptureDraft,
    *,
    session: AsyncSession,
    settings,
    now_dt: datetime | None = None,
) -> AdvisorOrchestrationResult:
    provider = get_ai_advisor_provider(settings)
    gate = AdvisorUsageGate(session, settings)
    model_name = getattr(settings, "openrouter_advisor_model", "openai/gpt-4o-mini")
    provider_name = getattr(settings, "advisor_provider", "disabled")

    orchestrator = AdvisorOrchestrator(
        provider=provider,
        gate=gate,
        provider_name=provider_name,
        model_name=model_name,
        context_validator=None,
    )

    request = AdvisorRequest(
        text=draft.text,
        advisor_intent=draft.advisor_intent,
        confidence=draft.confidence,
    )

    result = await orchestrator.run(request, now_dt=now_dt)
    result = await _enforce_settings_intent(draft, result, now_dt=now_dt)
    return await _enforce_checkin_fact_intent(draft, result, now_dt=now_dt)
