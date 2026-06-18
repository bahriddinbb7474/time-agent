from __future__ import annotations

from dataclasses import dataclass


_SUPPORTED_PROVIDERS = frozenset({"openrouter", "fake"})


@dataclass(frozen=True, slots=True)
class AdvisorRuntimeStatus:
    enabled: bool
    provider_configured: bool
    key_present: bool
    request_limit: int
    cost_limit_usd: float
    configuration_ready: bool
    safe: bool
    blockers: tuple[str, ...]


class AdvisorRuntimeService:
    """Process-local Advisor switch. A process restart always returns to OFF."""

    def __init__(self) -> None:
        self._enabled = False

    def status(self, settings) -> AdvisorRuntimeStatus:
        provider = str(getattr(settings, "advisor_provider", "disabled") or "disabled")
        key_present = bool(str(getattr(settings, "openrouter_api_key", "") or "").strip())
        request_limit = int(getattr(settings, "llm_daily_request_limit", 0) or 0)
        cost_limit = float(getattr(settings, "llm_daily_cost_usd_limit", 0.0) or 0.0)

        blockers: list[str] = []
        if provider == "disabled":
            blockers.append("provider_disabled")
        elif provider not in _SUPPORTED_PROVIDERS:
            blockers.append("provider_unsupported")
        if not key_present:
            blockers.append("key_missing")
        if request_limit <= 0:
            blockers.append("request_limit_unsafe")
        if cost_limit <= 0.0:
            blockers.append("cost_limit_unsafe")

        configuration_ready = not blockers
        return AdvisorRuntimeStatus(
            enabled=self._enabled,
            provider_configured=provider in _SUPPORTED_PROVIDERS,
            key_present=key_present,
            request_limit=request_limit,
            cost_limit_usd=cost_limit,
            configuration_ready=configuration_ready,
            safe=(not self._enabled) or configuration_ready,
            blockers=tuple(blockers),
        )

    def enable(self, settings) -> AdvisorRuntimeStatus:
        status = self.status(settings)
        if status.configuration_ready:
            self._enabled = True
        return self.status(settings)

    def disable(self) -> None:
        self._enabled = False


advisor_runtime = AdvisorRuntimeService()
