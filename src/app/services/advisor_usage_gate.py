from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_limit_service import ApiLimitDecision, ApiLimitService
from app.services.api_usage_service import ApiUsageService

log = logging.getLogger("time-agent.advisor_usage_gate")


@dataclass(frozen=True)
class LlmGateResult:
    """Result of a pre-call LLM gate check."""
    allowed: bool
    decision: ApiLimitDecision


class AdvisorUsageGate:
    """
    Thin orchestration layer that enforces the usage safety contract before
    any real LLM call:

        check()  →  (if allowed) call provider  →  record_success() / record_error()

    No prompt, response, transcript, or user text is ever accepted or stored.
    Stage 19.4 wires this into OpenRouterAdvisorProvider.
    """

    def __init__(self, session: AsyncSession, config) -> None:
        self._session = session
        self._config = config

    async def check(
        self,
        *,
        provider: str,
        model: str,
        usage_date: date | None = None,
    ) -> LlmGateResult:
        """
        Check the LLM hard limit before calling the provider.

        If blocked: records a limit_exceeded entry and returns allowed=False.
        If allowed:  returns allowed=True; caller may proceed to call the provider.
        No prompt or user text accepted.
        """
        decision = await ApiLimitService(self._session, self._config).check_llm(
            usage_date=usage_date,
        )
        if not decision.allowed:
            await ApiUsageService(self._session).record_limit_exceeded(
                provider=provider,
                service_type="llm",
                model=model,
            )
            log.info(
                "LLM gate blocked: reason=%s limit=%s current=%s limit_value=%s",
                decision.reason,
                decision.limit_name,
                decision.current_value,
                decision.limit_value,
            )
        return LlmGateResult(allowed=decision.allowed, decision=decision)

    async def record_success(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        """Record a successful LLM call. No prompt or response text accepted."""
        await ApiUsageService(self._session).record_llm(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            status="success",
        )

    async def record_error(
        self,
        *,
        provider: str,
        model: str,
    ) -> None:
        """Record a failed LLM call. No error message or user text accepted."""
        await ApiUsageService(self._session).record_llm(
            provider=provider,
            model=model,
            status="error",
        )
