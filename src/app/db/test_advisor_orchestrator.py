"""
Stage 19.7 — AdvisorOrchestrator tests.

Verifies:
- disabled provider returns safe no-advisor result without gate or provider call;
- gate blocked → provider not called, blocked_by_limit=True;
- gate allowed → provider called exactly once;
- success path calls gate.record_success with correct tokens/cost;
- success path does NOT call gate.record_error;
- provider error calls gate.record_error, not record_success;
- provider error returns provider_error=True, used_advisor=False;
- validation_result is set (ProposalValidationResult) after success;
- used_advisor=True only on clean success + validation;
- context conflict in validator yields valid=False in validation_result;
- run() signature has no prompt/text/transcript/raw_payload params;
- AdvisorOrchestrationResult has no private-data fields;
- one run() call → at most one provider.advise() call.

No real HTTP calls. No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_advisor_orchestrator.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.core.time import APP_TZ, now_tz
from app.services.advisor_orchestrator import AdvisorOrchestrationResult, AdvisorOrchestrator
from app.services.advisor_proposal_validator import ProposalValidationResult
from app.services.advisor_usage_gate import LlmGateResult
from app.services.ai_advisor_provider import (
    AdvisorProposal,
    AdvisorRequest,
    DisabledAIAdvisorProvider,
    FakeAIAdvisorProvider,
)
from app.services.api_limit_service import ApiLimitDecision
from app.services.validation_result import (
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)

# ── Fixed time anchor ─────────────────────────────────────────────────────────
_NOW_DT = now_tz().replace(hour=12, minute=0, second=0, microsecond=0)
_PROVIDER_NAME = "openrouter"
_MODEL_NAME = "openai/gpt-4o-mini"

_REQUEST = AdvisorRequest(text="Купить молоко", advisor_intent="capture", confidence=1.0)


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _allowed_decision() -> ApiLimitDecision:
    return ApiLimitDecision(
        allowed=True, reason=None, limit_name=None, current_value=0, limit_value=0
    )


def _blocked_decision() -> ApiLimitDecision:
    return ApiLimitDecision(
        allowed=False,
        reason="llm_request_limit",
        limit_name="LLM_DAILY_REQUEST_LIMIT",
        current_value=5,
        limit_value=5,
    )


def _mock_gate(*, allowed: bool) -> MagicMock:
    decision = _allowed_decision() if allowed else _blocked_decision()
    gate = MagicMock()
    gate.check = AsyncMock(return_value=LlmGateResult(allowed=allowed, decision=decision))
    gate.record_success = AsyncMock(return_value=None)
    gate.record_error = AsyncMock(return_value=None)
    return gate


def _make_proposal(
    *,
    proposal_type: str = "later",
    title: str | None = "Купить молоко",
    when_text: str | None = None,
    model: str = _MODEL_NAME,
    input_tokens: int = 50,
    output_tokens: int = 30,
    estimated_cost_usd: float = 0.0001,
    error: bool = False,
    needs_confirmation: bool = True,
) -> AdvisorProposal:
    return AdvisorProposal(
        intent="capture",
        proposal_type=proposal_type,
        title=title,
        description=None,
        category="personal",
        when_text=when_text,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=needs_confirmation,
        needs_clarification=False,
        user_message="Добавить в Later?" if not error else "Ошибка провайдера.",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        error=error,
    )


class _FixedProposalProvider:
    """Test-only provider that returns a pre-built proposal."""
    def __init__(self, proposal: AdvisorProposal) -> None:
        self._proposal = proposal
        self.call_count = 0

    async def advise(self, request: AdvisorRequest) -> AdvisorProposal:
        self.call_count += 1
        return self._proposal


def _mock_provider(*, error: bool = False) -> MagicMock:
    proposal = _make_proposal(error=error)
    provider = MagicMock()
    provider.advise = AsyncMock(return_value=proposal)
    return provider


def _make_orchestrator(
    provider,
    gate,
    *,
    context_validator=None,
) -> AdvisorOrchestrator:
    return AdvisorOrchestrator(
        provider=provider,
        gate=gate,
        provider_name=_PROVIDER_NAME,
        model_name=_MODEL_NAME,
        context_validator=context_validator,
    )


def _mock_conflict_cv() -> MagicMock:
    cv = MagicMock()
    cv.validate_event = AsyncMock(return_value=ValidationResult(
        status=ValidationStatus.CONFLICT,
        severity=ValidationSeverity.HARD_BLOCK,
        reason_code="prayer_conflict",
        message="В это время намаз.",
    ))
    return cv


# ── Tests ──────────────────────────────────────────────────────────────────────


async def test_disabled_provider_returns_no_advisor_result():
    gate = _mock_gate(allowed=True)
    provider = DisabledAIAdvisorProvider()
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.used_advisor is False
    assert result.blocked_by_limit is False
    assert result.provider_error is False
    assert result.validation_result is None
    assert result.reason_code == "advisor_disabled"
    print("PASS: test_disabled_provider_returns_no_advisor_result")


async def test_disabled_provider_does_not_call_gate():
    gate = _mock_gate(allowed=True)
    provider = DisabledAIAdvisorProvider()
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.check.assert_not_called()
    gate.record_success.assert_not_called()
    gate.record_error.assert_not_called()
    print("PASS: test_disabled_provider_does_not_call_gate")


async def test_gate_blocked_returns_blocked_result():
    gate = _mock_gate(allowed=False)
    provider = _mock_provider()
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.blocked_by_limit is True
    assert result.used_advisor is False
    assert result.provider_error is False
    assert result.validation_result is None
    assert result.reason_code == "llm_limit_exceeded"
    print("PASS: test_gate_blocked_returns_blocked_result")


async def test_gate_blocked_does_not_call_provider():
    gate = _mock_gate(allowed=False)
    provider = _mock_provider()
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    provider.advise.assert_not_called()
    print("PASS: test_gate_blocked_does_not_call_provider")


async def test_gate_allowed_calls_provider_exactly_once():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider()
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert provider.advise.call_count == 1
    print("PASS: test_gate_allowed_calls_provider_exactly_once")


async def test_success_calls_gate_check():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider()
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.check.assert_called_once_with(
        provider=_PROVIDER_NAME, model=_MODEL_NAME
    )
    print("PASS: test_success_calls_gate_check")


async def test_success_records_success_with_tokens():
    gate = _mock_gate(allowed=True)
    proposal = _make_proposal(input_tokens=120, output_tokens=45, estimated_cost_usd=0.0003)
    provider = _FixedProposalProvider(proposal)
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.record_success.assert_called_once_with(
        provider=_PROVIDER_NAME,
        model=_MODEL_NAME,
        input_tokens=120,
        output_tokens=45,
        estimated_cost_usd=0.0003,
    )
    print("PASS: test_success_records_success_with_tokens")


async def test_success_does_not_record_error():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider(error=False)
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.record_error.assert_not_called()
    print("PASS: test_success_does_not_record_error")


async def test_provider_error_calls_record_error():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider(error=True)
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.record_error.assert_called_once_with(
        provider=_PROVIDER_NAME, model=_MODEL_NAME
    )
    print("PASS: test_provider_error_calls_record_error")


async def test_provider_error_does_not_call_record_success():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider(error=True)
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    gate.record_success.assert_not_called()
    print("PASS: test_provider_error_does_not_call_record_success")


async def test_provider_error_result_fields():
    gate = _mock_gate(allowed=True)
    provider = _mock_provider(error=True)
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.provider_error is True
    assert result.used_advisor is False
    assert result.blocked_by_limit is False
    assert result.validation_result is None
    assert result.reason_code == "provider_error"
    print("PASS: test_provider_error_result_fields")


async def test_validation_result_set_after_success():
    gate = _mock_gate(allowed=True)
    provider = FakeAIAdvisorProvider()
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.used_advisor is True
    assert result.validation_result is not None
    assert isinstance(result.validation_result, ProposalValidationResult)
    print("PASS: test_validation_result_set_after_success")


async def test_used_advisor_true_on_clean_success():
    gate = _mock_gate(allowed=True)
    provider = FakeAIAdvisorProvider()
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.used_advisor is True
    assert result.blocked_by_limit is False
    assert result.provider_error is False
    print("PASS: test_used_advisor_true_on_clean_success")


async def test_context_conflict_in_validator_yields_invalid_result():
    """Prayer conflict detected in validator → validation_result.valid=False, but used_advisor=True."""
    gate = _mock_gate(allowed=True)
    # Proposal with parseable future when_text so context validator is consulted
    proposal = _make_proposal(proposal_type="task", title="Задача", when_text="23:59")
    provider = _FixedProposalProvider(proposal)
    cv = _mock_conflict_cv()
    orch = _make_orchestrator(provider, gate, context_validator=cv)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert result.used_advisor is True
    assert result.provider_error is False
    assert result.validation_result is not None
    assert result.validation_result.valid is False
    assert result.validation_result.safe_proposal.proposal_type == "clarification"
    cv.validate_event.assert_called_once()
    print("PASS: test_context_conflict_in_validator_yields_invalid_result")


async def test_run_signature_has_no_private_params():
    sig = inspect.signature(AdvisorOrchestrator.run)
    params = set(sig.parameters.keys())
    forbidden = {"text", "prompt", "raw_text", "transcript", "response", "api_key", "session"}
    present = params & forbidden
    assert not present, f"run() must not have private params: {present}"
    print("PASS: test_run_signature_has_no_private_params")


async def test_result_has_no_private_data_fields():
    field_names = {f.name for f in dataclasses.fields(AdvisorOrchestrationResult)}
    forbidden = {"text", "prompt", "response", "transcript", "raw_text", "raw_payload"}
    present = field_names & forbidden
    assert not present, f"AdvisorOrchestrationResult must not have private-data fields: {present}"
    print("PASS: test_result_has_no_private_data_fields")


async def test_one_run_at_most_one_provider_call():
    gate = _mock_gate(allowed=True)
    proposal = _make_proposal()
    provider = _FixedProposalProvider(proposal)
    orch = _make_orchestrator(provider, gate)
    await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert provider.call_count <= 1, f"provider called {provider.call_count} times, expected at most 1"
    print("PASS: test_one_run_at_most_one_provider_call")


async def test_result_shape_is_complete():
    gate = _mock_gate(allowed=True)
    provider = FakeAIAdvisorProvider()
    orch = _make_orchestrator(provider, gate)
    result = await orch.run(_REQUEST, now_dt=_NOW_DT)
    assert isinstance(result, AdvisorOrchestrationResult)
    assert isinstance(result.used_advisor, bool)
    assert isinstance(result.blocked_by_limit, bool)
    assert isinstance(result.provider_error, bool)
    assert isinstance(result.reason_code, str)
    assert isinstance(result.user_message, str)
    print("PASS: test_result_shape_is_complete")


# ── Runner ────────────────────────────────────────────────────────────────────


ALL_TESTS = [
    test_disabled_provider_returns_no_advisor_result,
    test_disabled_provider_does_not_call_gate,
    test_gate_blocked_returns_blocked_result,
    test_gate_blocked_does_not_call_provider,
    test_gate_allowed_calls_provider_exactly_once,
    test_success_calls_gate_check,
    test_success_records_success_with_tokens,
    test_success_does_not_record_error,
    test_provider_error_calls_record_error,
    test_provider_error_does_not_call_record_success,
    test_provider_error_result_fields,
    test_validation_result_set_after_success,
    test_used_advisor_true_on_clean_success,
    test_context_conflict_in_validator_yields_invalid_result,
    test_run_signature_has_no_private_params,
    test_result_has_no_private_data_fields,
    test_one_run_at_most_one_provider_call,
    test_result_shape_is_complete,
]


def main() -> None:
    async def _run_all():
        for fn in ALL_TESTS:
            await fn()

    asyncio.run(_run_all())
    print(f"\nALL {len(ALL_TESTS)} TESTS PASSED")  # 18


if __name__ == "__main__":
    main()
