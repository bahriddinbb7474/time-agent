from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiUsageRecord

log = logging.getLogger("time-agent.api_usage")

_ALLOWED_STATUSES = frozenset({"success", "error", "limit_exceeded"})
_ALLOWED_SERVICE_TYPES = frozenset({"stt", "llm"})


class ApiUsageValidationError(ValueError):
    pass


def _validate_token_count(name: str, value: object) -> int:
    """Return a validated non-negative token count; None converts to 0.

    Accepts only plain int (not bool, not float, not str). None maps to 0.
    """
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiUsageValidationError(
            f"{name} must be a non-negative integer (got {type(value).__name__})"
        )
    if value < 0:
        raise ApiUsageValidationError(f"{name} must be >= 0, got {value}")
    return value


class ApiUsageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        provider: str,
        service_type: str,
        model: str,
        request_count: int = 1,
        audio_seconds: float = 0.0,
        estimated_cost_usd: float = 0.0,
        status: str = "success",
        input_tokens: int | None = 0,
        output_tokens: int | None = 0,
        occurred_at: datetime | None = None,
    ) -> ApiUsageRecord:
        input_tok = _validate_token_count("input_tokens", input_tokens)
        output_tok = _validate_token_count("output_tokens", output_tokens)
        self._validate(
            provider=provider,
            service_type=service_type,
            model=model,
            request_count=request_count,
            audio_seconds=audio_seconds,
            estimated_cost_usd=estimated_cost_usd,
            status=status,
        )
        ts = occurred_at if occurred_at is not None else datetime.now(timezone.utc)
        entry = ApiUsageRecord(
            created_at=ts,
            usage_date=ts.date(),
            provider=provider,
            service_type=service_type,
            model=model,
            request_count=request_count,
            audio_seconds=audio_seconds,
            estimated_cost_usd=estimated_cost_usd,
            status=status,
            input_tokens=input_tok,
            output_tokens=output_tok,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def record_stt(
        self,
        *,
        provider: str,
        model: str,
        audio_seconds: float = 0.0,
        estimated_cost_usd: float = 0.0,
        status: str = "success",
        occurred_at: datetime | None = None,
    ) -> ApiUsageRecord:
        return await self.record(
            provider=provider,
            service_type="stt",
            model=model,
            audio_seconds=audio_seconds,
            estimated_cost_usd=estimated_cost_usd,
            status=status,
            input_tokens=0,
            output_tokens=0,
            occurred_at=occurred_at,
        )

    def _validate(
        self,
        *,
        provider: str,
        service_type: str,
        model: str,
        request_count: int,
        audio_seconds: float,
        estimated_cost_usd: float,
        status: str,
    ) -> None:
        if not provider or not provider.strip():
            raise ApiUsageValidationError("provider must not be empty")
        if service_type not in _ALLOWED_SERVICE_TYPES:
            raise ApiUsageValidationError(
                f"service_type must be one of {sorted(_ALLOWED_SERVICE_TYPES)!r}, got {service_type!r}"
            )
        if not model or not model.strip():
            raise ApiUsageValidationError("model must not be empty")
        if request_count < 1:
            raise ApiUsageValidationError(
                f"request_count must be >= 1, got {request_count}"
            )
        if not math.isfinite(audio_seconds) or audio_seconds < 0:
            raise ApiUsageValidationError(
                f"audio_seconds must be finite and >= 0, got {audio_seconds}"
            )
        if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
            raise ApiUsageValidationError(
                f"estimated_cost_usd must be finite and >= 0, got {estimated_cost_usd}"
            )
        if status not in _ALLOWED_STATUSES:
            raise ApiUsageValidationError(
                f"status must be one of {sorted(_ALLOWED_STATUSES)!r}, got {status!r}"
            )
