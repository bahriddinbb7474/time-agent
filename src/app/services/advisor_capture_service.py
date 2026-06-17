"""
Stage 19.7-D — Thin integration layer between capture flow and advisor pipeline.

Pure orchestration: no Telegram types, no session lifecycle management.
No prompt, response, transcript, or user text is stored.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.advisor_orchestrator import AdvisorOrchestrationResult, AdvisorOrchestrator
from app.services.advisor_usage_gate import AdvisorUsageGate
from app.services.ai_advisor_provider import AdvisorProposal, AdvisorRequest, get_ai_advisor_provider
from app.services.capture_router_service import CaptureDraft

log = logging.getLogger("time-agent.advisor.capture")

_ADVISOR_INTENTS = frozenset({"help", "settings", "unknown"})

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


def build_safe_advisor_proposal_json(proposal: AdvisorProposal) -> str:
    safe = {k: getattr(proposal, k) for k in _SAFE_PROPOSAL_KEYS}
    return json.dumps(safe, ensure_ascii=False)


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

    return await orchestrator.run(request, now_dt=now_dt)
