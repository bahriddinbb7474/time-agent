from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.api_usage_service import ApiUsageService, DailyUsageSummary

log = logging.getLogger("time-agent.api_limit")

# Structured reason codes — stable strings, never shown raw to the user
REASON_STT_REQUEST_LIMIT = "stt_request_limit"
REASON_STT_SECONDS_LIMIT = "stt_seconds_limit"
REASON_LLM_REQUEST_LIMIT = "llm_request_limit"
REASON_LLM_COST_LIMIT = "llm_cost_limit"


@dataclass(frozen=True)
class ApiLimitDecision:
    allowed: bool
    reason: str | None       # reason code; None when allowed
    limit_name: str | None   # canonical env-var name; None when allowed
    current_value: int | float
    limit_value: int | float


_DECISION_ALLOWED = ApiLimitDecision(
    allowed=True,
    reason=None,
    limit_name=None,
    current_value=0,
    limit_value=0,
)


class ApiLimitService:
    """Read-only preflight guard for API hard limits.

    Checks current daily usage against configured limits and returns a
    structured decision without making any HTTP calls or DB writes.

    Concurrency note: protects a single process only.  Multi-instance
    deployments require a distributed lock or DB-level transaction.
    """

    def __init__(self, session: AsyncSession, config) -> None:
        self._session = session
        self._config = config

    async def check_stt(
        self,
        planned_seconds: float,
        usage_date: date,
    ) -> ApiLimitDecision:
        """Return allowed/blocked decision for an upcoming STT request.

        planned_seconds: audio duration from Telegram voice metadata (before
        the provider is called).  Used for the seconds-limit preflight only;
        it is never recorded as actual provider usage here.
        """
        summary = await ApiUsageService(self._session).get_daily_summary(usage_date)
        return self._evaluate_stt(summary, planned_seconds)

    async def check_llm(
        self,
        planned_requests: int = 1,
        planned_cost_usd: float = 0.0,
        usage_date: date | None = None,
    ) -> ApiLimitDecision:
        """Return allowed/blocked decision for an upcoming LLM request.

        Used for future LLM integration (Stage 19+).  Not called at runtime
        during Stage 18.6-D since no real LLM provider is connected.
        """
        from app.core.time import now_tz
        d = usage_date if usage_date is not None else now_tz().date()
        summary = await ApiUsageService(self._session).get_daily_summary(d)
        return self._evaluate_llm(summary, planned_requests, planned_cost_usd)

    # ── Internal evaluators (pure, no I/O) ──────────────────────────────────

    def _evaluate_stt(
        self, summary: DailyUsageSummary, planned_seconds: float
    ) -> ApiLimitDecision:
        req_limit = self._config.stt_daily_request_limit
        if req_limit > 0:
            current = summary.stt_request_count
            if current + 1 > req_limit:
                return ApiLimitDecision(
                    allowed=False,
                    reason=REASON_STT_REQUEST_LIMIT,
                    limit_name="STT_DAILY_REQUEST_LIMIT",
                    current_value=current,
                    limit_value=req_limit,
                )

        sec_limit = self._config.stt_daily_seconds_limit
        if sec_limit > 0:
            current_sec = summary.stt_audio_seconds
            if current_sec + planned_seconds > sec_limit:
                return ApiLimitDecision(
                    allowed=False,
                    reason=REASON_STT_SECONDS_LIMIT,
                    limit_name="STT_DAILY_SECONDS_LIMIT",
                    current_value=current_sec,
                    limit_value=sec_limit,
                )

        return _DECISION_ALLOWED

    def _evaluate_llm(
        self,
        summary: DailyUsageSummary,
        planned_requests: int,
        planned_cost_usd: float,
    ) -> ApiLimitDecision:
        req_limit = self._config.llm_daily_request_limit
        if req_limit > 0:
            current = summary.llm_request_count
            if current + planned_requests > req_limit:
                return ApiLimitDecision(
                    allowed=False,
                    reason=REASON_LLM_REQUEST_LIMIT,
                    limit_name="LLM_DAILY_REQUEST_LIMIT",
                    current_value=current,
                    limit_value=req_limit,
                )

        cost_limit = self._config.llm_daily_cost_usd_limit
        if cost_limit > 0.0:
            current_cost = summary.llm_estimated_cost_usd
            if current_cost + planned_cost_usd > cost_limit:
                return ApiLimitDecision(
                    allowed=False,
                    reason=REASON_LLM_COST_LIMIT,
                    limit_name="LLM_DAILY_COST_USD_LIMIT",
                    current_value=current_cost,
                    limit_value=cost_limit,
                )

        return _DECISION_ALLOWED
