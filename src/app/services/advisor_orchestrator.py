"""
Stage 19.7 — Advisor orchestration service.

Orchestrates the LLM advisor pipeline in a single, safe call:

    disabled-check → gate-check → provider.advise() → record-usage → validate → result

Invariants:
- If provider is disabled, returns immediately — no gate call, no provider call.
- If gate blocks, provider is not called.
- Provider is called at most once per run() invocation.
- Usage is always recorded after a provider call (success or error).
- Proposal is always validated before returning to the caller.
- No task, daily-target, or settings changes are made.
- No prompt, response, transcript, or user text is stored.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.advisor_proposal_validator import (
    ProposalValidationResult,
    validate_advisor_proposal,
)
from app.services.advisor_usage_gate import AdvisorUsageGate
from app.services.ai_advisor_provider import AdvisorRequest, DisabledAIAdvisorProvider

log = logging.getLogger("time-agent.advisor.orchestrator")


# ── Result DTO ────────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class AdvisorOrchestrationResult:
    """
    Safe result of one orchestrated advisor call.

    No prompt, response, or user text stored here.
    """
    used_advisor: bool
    blocked_by_limit: bool
    provider_error: bool
    validation_result: ProposalValidationResult | None
    user_message: str
    reason_code: str


# ── Orchestrator ──────────────────────────────────────────────────────────────


class AdvisorOrchestrator:
    """
    Coordinates the full advisor pipeline for a single capture request.

    Parameters
    ----------
    provider:
        An AIAdvisorProvider instance (disabled / fake / openrouter).
    gate:
        An AdvisorUsageGate instance wired to the active DB session and config.
    provider_name:
        String identifier used for usage tracking (e.g. "openrouter", "fake").
    model_name:
        Model string used for usage tracking (e.g. "openai/gpt-4o-mini").
    context_validator:
        Optional ContextValidator for prayer/sleep/protected-slot checks.
        If None, context conflict checks are skipped inside the proposal validator.
    """

    def __init__(
        self,
        provider: Any,
        gate: AdvisorUsageGate,
        *,
        provider_name: str,
        model_name: str,
        context_validator: Any | None = None,
    ) -> None:
        self._provider = provider
        self._gate = gate
        self._provider_name = provider_name
        self._model_name = model_name
        self._context_validator = context_validator

    async def run(
        self,
        request: AdvisorRequest,
        *,
        now_dt: datetime | None = None,
    ) -> AdvisorOrchestrationResult:
        """
        Run the advisor pipeline for a single AdvisorRequest.

        Guarantees: at most one provider.advise() call per run() invocation.
        """
        # ── Step 1: disabled provider → early exit, no gate or provider call ──
        if isinstance(self._provider, DisabledAIAdvisorProvider):
            return AdvisorOrchestrationResult(
                used_advisor=False,
                blocked_by_limit=False,
                provider_error=False,
                validation_result=None,
                user_message="",
                reason_code="advisor_disabled",
            )

        # ── Step 2: check usage gate before any provider call ─────────────────
        gate_result = await self._gate.check(
            provider=self._provider_name,
            model=self._model_name,
        )
        if not gate_result.allowed:
            log.info(
                "Advisor gate blocked: %s",
                gate_result.decision.reason or "limit_exceeded",
            )
            return AdvisorOrchestrationResult(
                used_advisor=False,
                blocked_by_limit=True,
                provider_error=False,
                validation_result=None,
                user_message="Лимит AI запросов исчерпан на сегодня.",
                reason_code="llm_limit_exceeded",
            )

        # ── Step 3: call provider — exactly once ──────────────────────────────
        proposal = await self._provider.advise(request)

        # ── Step 4: record usage (error path) ────────────────────────────────
        if proposal.error:
            await self._gate.record_error(
                provider=self._provider_name,
                model=proposal.model or self._model_name,
            )
            return AdvisorOrchestrationResult(
                used_advisor=False,
                blocked_by_limit=False,
                provider_error=True,
                validation_result=None,
                user_message=proposal.user_message,
                reason_code="provider_error",
            )

        # ── Step 4: record usage (success path) ──────────────────────────────
        await self._gate.record_success(
            provider=self._provider_name,
            model=proposal.model or self._model_name,
            input_tokens=proposal.input_tokens,
            output_tokens=proposal.output_tokens,
            estimated_cost_usd=proposal.estimated_cost_usd,
        )

        # ── Step 5: validate proposal (always runs before returning) ──────────
        validation = await validate_advisor_proposal(
            proposal,
            now_dt=now_dt,
            context_validator=self._context_validator,
        )

        return AdvisorOrchestrationResult(
            used_advisor=True,
            blocked_by_limit=False,
            provider_error=False,
            validation_result=validation,
            user_message=validation.user_message,
            reason_code=validation.reason_code,
        )
