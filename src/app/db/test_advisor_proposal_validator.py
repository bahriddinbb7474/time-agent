"""
Stage 19.6 — AdvisorProposalValidator tests.

Verifies:
- help_text / none / clarification pass through safely
- task proposal with valid title/category passes
- invalid category normalized to "other"
- empty / whitespace-only title → needs_clarification
- past when_text → invalid/needs_clarification
- future when_text → passes
- unparseable when_text → passes gracefully (no crash)
- prayer/protected conflict (mocked ContextValidator CONFLICT) → invalid
- context validator not called when normalized_when is None
- settings_change valid target_name + value → valid proposal only, no DB write
- settings_change missing target_name → needs_clarification
- settings_change invalid / zero / negative value → needs_clarification
- actionable proposals (task/later/boss/settings_change) always have needs_confirmation=True
- validator signature has no session / provider / api_key params

No real HTTP calls. No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_advisor_proposal_validator.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.core.time import APP_TZ, now_tz
from app.services.ai_advisor_provider import AdvisorProposal
from app.services.advisor_proposal_validator import (
    ProposalValidationResult,
    validate_advisor_proposal,
)
from app.services.validation_result import (
    ConflictType,
    ValidationResult,
    ValidationSeverity,
    ValidationStatus,
)

_MODEL = "openai/gpt-4o-mini"

# ── Reference times ────────────────────────────────────────────────────────────
# Use today's date from now_tz() so parse_add_payload (which calls now_tz().date()
# internally) and our now_dt anchor are always on the same calendar day.

_TODAY = now_tz()
_NOW_DT = _TODAY.replace(hour=12, minute=0, second=0, microsecond=0)
# 1 AM today is always past relative to noon today
_PAST_WHEN_TEXT = "01:00"
# 11:59 PM today is always future relative to noon today
_FUTURE_WHEN_TEXT = "23:59"


# ── Proposal factory helpers ───────────────────────────────────────────────────


def _proposal(
    *,
    proposal_type: str = "task",
    intent: str = "capture",
    title: str | None = "Купить молоко",
    category: str | None = "personal",
    when_text: str | None = None,
    target_name: str | None = None,
    target_value: str | None = None,
    target_unit: str | None = None,
    needs_confirmation: bool = True,
    needs_clarification: bool = False,
    user_message: str = "Добавить задачу?",
) -> AdvisorProposal:
    return AdvisorProposal(
        intent=intent,
        proposal_type=proposal_type,
        title=title,
        description=None,
        category=category,
        when_text=when_text,
        target_name=target_name,
        target_value=target_value,
        target_unit=target_unit,
        needs_confirmation=needs_confirmation,
        needs_clarification=needs_clarification,
        user_message=user_message,
        model=_MODEL,
        input_tokens=50,
        output_tokens=30,
        estimated_cost_usd=0.0,
        error=False,
    )


def _mock_context_validator(*, conflict: bool, hard: bool = True) -> MagicMock:
    if conflict:
        result = ValidationResult(
            status=ValidationStatus.CONFLICT,
            severity=ValidationSeverity.HARD_BLOCK if hard else ValidationSeverity.WARNING,
            reason_code="prayer_conflict",
            message="В это время намаз.",
        )
    else:
        result = ValidationResult(
            status=ValidationStatus.VALID,
            severity=ValidationSeverity.INFO,
            reason_code="ok",
            message="No conflict.",
        )
    cv = MagicMock()
    cv.validate_event = AsyncMock(return_value=result)
    return cv


# ── Sync tests (run via asyncio.run) ──────────────────────────────────────────


async def test_help_text_passes_through_safely():
    # help_text is informational; LLM says needs_confirmation=False, validator preserves it
    p = _proposal(proposal_type="help_text", intent="help", title=None, needs_confirmation=False)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.needs_clarification is False
    assert result.safe_proposal.proposal_type == "help_text"
    assert result.safe_proposal.needs_confirmation is False
    print("PASS: test_help_text_passes_through_safely")


async def test_none_proposal_passes_through():
    p = _proposal(proposal_type="none", title=None)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.needs_clarification is False
    print("PASS: test_none_proposal_passes_through")


async def test_clarification_passes_through_with_flag():
    p = _proposal(proposal_type="clarification", title=None)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.needs_clarification is True
    print("PASS: test_clarification_passes_through_with_flag")


async def test_task_valid_proposal_passes():
    p = _proposal(proposal_type="task", title="Позвонить врачу", category="health")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True, f"expected valid, got reason_code={result.reason_code!r}"
    assert result.needs_clarification is False
    assert result.safe_proposal.proposal_type == "task"
    print("PASS: test_task_valid_proposal_passes")


async def test_invalid_category_normalized_to_other():
    p = _proposal(proposal_type="task", title="Задача", category="gym")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.normalized_category == "other", f"got {result.normalized_category!r}"
    assert result.safe_proposal.category == "other"
    print("PASS: test_invalid_category_normalized_to_other")


async def test_valid_category_preserved():
    p = _proposal(proposal_type="task", title="Встреча", category="work")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.normalized_category == "work"
    assert result.safe_proposal.category == "work"
    print("PASS: test_valid_category_preserved")


async def test_empty_title_returns_clarification():
    p = _proposal(proposal_type="task", title="")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False, "empty title must be invalid"
    assert result.needs_clarification is True
    assert result.reason_code == "empty_title"
    assert result.safe_proposal.proposal_type == "clarification"
    print("PASS: test_empty_title_returns_clarification")


async def test_whitespace_only_title_returns_clarification():
    p = _proposal(proposal_type="task", title="   ")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.needs_clarification is True
    assert result.reason_code == "empty_title"
    print("PASS: test_whitespace_only_title_returns_clarification")


async def test_none_title_returns_clarification():
    p = _proposal(proposal_type="task", title=None)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.needs_clarification is True
    print("PASS: test_none_title_returns_clarification")


async def test_past_when_text_returns_invalid():
    # "01:00" is 1 AM today — always in the past relative to noon today
    p = _proposal(proposal_type="task", title="Задача", when_text=_PAST_WHEN_TEXT)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False, "past time must be invalid"
    assert result.needs_clarification is True
    assert result.reason_code == "past_time"
    print("PASS: test_past_when_text_returns_invalid")


async def test_future_when_text_passes():
    # "23:59" is 11:59 PM today — always future relative to noon today
    p = _proposal(proposal_type="task", title="Задача", when_text=_FUTURE_WHEN_TEXT)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True, f"future time must pass; got reason={result.reason_code!r}"
    assert result.normalized_when is not None
    print("PASS: test_future_when_text_passes")


async def test_unparseable_when_text_passes_gracefully():
    # LLM might produce unstructured text — must not crash the validator
    p = _proposal(proposal_type="task", title="Задача", when_text="через несколько дней")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True, "unparseable when_text must be allowed through"
    assert result.normalized_when is None
    print("PASS: test_unparseable_when_text_passes_gracefully")


async def test_prayer_conflict_invalidates_task():
    cv = _mock_context_validator(conflict=True, hard=True)
    p = _proposal(proposal_type="task", title="Задача", when_text=_FUTURE_WHEN_TEXT)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT, context_validator=cv)
    assert result.valid is False, "prayer conflict must invalidate proposal"
    assert result.needs_clarification is True
    assert result.safe_proposal.proposal_type == "clarification"
    cv.validate_event.assert_called_once()
    print("PASS: test_prayer_conflict_invalidates_task")


async def test_sleep_conflict_warning_also_invalidates_task():
    # Even WARNING severity conflicts block the proposal (validators > LLM)
    cv = _mock_context_validator(conflict=True, hard=False)
    p = _proposal(proposal_type="task", title="Задача", when_text=_FUTURE_WHEN_TEXT)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT, context_validator=cv)
    assert result.valid is False, "any context conflict must invalidate proposal"
    print("PASS: test_sleep_conflict_warning_also_invalidates_task")


async def test_no_conflict_with_cv_passes():
    cv = _mock_context_validator(conflict=False)
    p = _proposal(proposal_type="task", title="Задача", when_text=_FUTURE_WHEN_TEXT)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT, context_validator=cv)
    assert result.valid is True
    cv.validate_event.assert_called_once()
    print("PASS: test_no_conflict_with_cv_passes")


async def test_context_validator_not_called_when_no_when_text():
    cv = _mock_context_validator(conflict=True, hard=True)
    p = _proposal(proposal_type="task", title="Задача", when_text=None)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT, context_validator=cv)
    assert result.valid is True
    cv.validate_event.assert_not_called()
    print("PASS: test_context_validator_not_called_when_no_when_text")


async def test_settings_valid_passes_as_proposal_only():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        title=None,
        target_name="Вода",
        target_value="2",
        target_unit="л",
        user_message="Изменить цель воды?",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True, f"got reason={result.reason_code!r}"
    assert result.safe_proposal.proposal_type == "settings_change"
    assert result.safe_proposal.target_name == "Вода"
    assert result.safe_proposal.needs_confirmation is True
    # Validator must NOT have changed any DB (no session was involved at all)
    print("PASS: test_settings_valid_passes_as_proposal_only")


async def test_settings_missing_target_name_fails():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name=None,
        target_value="2",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.reason_code == "missing_target_name"
    assert result.safe_proposal.proposal_type == "clarification"
    print("PASS: test_settings_missing_target_name_fails")


async def test_settings_empty_target_name_fails():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name="   ",
        target_value="2",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.reason_code == "missing_target_name"
    print("PASS: test_settings_empty_target_name_fails")


async def test_settings_invalid_string_value_fails():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name="Вода",
        target_value="много",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.reason_code == "invalid_target_value"
    print("PASS: test_settings_invalid_string_value_fails")


async def test_settings_zero_value_fails():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name="Вода",
        target_value="0",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.reason_code == "invalid_target_value"
    print("PASS: test_settings_zero_value_fails")


async def test_settings_negative_value_fails():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name="Вода",
        target_value="-1",
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.reason_code == "invalid_target_value"
    print("PASS: test_settings_negative_value_fails")


async def test_task_enforces_confirmation_even_when_llm_returns_false():
    p = _proposal(proposal_type="task", title="Задача", needs_confirmation=False)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.safe_proposal.needs_confirmation is True, \
        "task must have needs_confirmation=True regardless of LLM output"
    print("PASS: test_task_enforces_confirmation_even_when_llm_returns_false")


async def test_later_enforces_confirmation():
    p = _proposal(proposal_type="later", title="Идея", needs_confirmation=False)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.safe_proposal.needs_confirmation is True
    print("PASS: test_later_enforces_confirmation")


async def test_boss_enforces_confirmation():
    p = _proposal(proposal_type="boss", title="Срочное", needs_confirmation=False)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.safe_proposal.needs_confirmation is True
    print("PASS: test_boss_enforces_confirmation")


async def test_settings_change_enforces_confirmation():
    p = _proposal(
        proposal_type="settings_change",
        intent="settings",
        target_name="Шаги",
        target_value="10000",
        needs_confirmation=False,
    )
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is True
    assert result.safe_proposal.needs_confirmation is True
    print("PASS: test_settings_change_enforces_confirmation")


async def test_validator_no_db_session_param():
    sig = inspect.signature(validate_advisor_proposal)
    params = set(sig.parameters.keys())
    forbidden = {"session", "db", "provider", "api_key", "client"}
    present = params & forbidden
    assert not present, f"validate_advisor_proposal must not accept: {present}"
    print("PASS: test_validator_no_db_session_param")


async def test_safe_proposal_is_always_returned():
    """Validator always returns a safe_proposal, even for invalid input."""
    p = _proposal(proposal_type="task", title="")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.safe_proposal is not None
    assert isinstance(result.safe_proposal, AdvisorProposal)
    assert result.safe_proposal.error is False
    print("PASS: test_safe_proposal_is_always_returned")


async def test_invalid_safe_proposal_downgraded_to_clarification():
    p = _proposal(proposal_type="task", title=None)
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert result.valid is False
    assert result.safe_proposal.proposal_type == "clarification"
    assert result.safe_proposal.needs_clarification is True
    assert result.safe_proposal.title is None
    assert result.safe_proposal.when_text is None
    assert result.safe_proposal.target_name is None
    print("PASS: test_invalid_safe_proposal_downgraded_to_clarification")


async def test_valid_proposal_result_has_correct_shape():
    p = _proposal(proposal_type="task", title="Тест", category="work")
    result = await validate_advisor_proposal(p, now_dt=_NOW_DT)
    assert isinstance(result, ProposalValidationResult)
    assert isinstance(result.valid, bool)
    assert isinstance(result.needs_clarification, bool)
    assert isinstance(result.reason_code, str)
    assert isinstance(result.user_message, str)
    print("PASS: test_valid_proposal_result_has_correct_shape")


# ── Runner ────────────────────────────────────────────────────────────────────


ALL_TESTS = [
    test_help_text_passes_through_safely,
    test_none_proposal_passes_through,
    test_clarification_passes_through_with_flag,
    test_task_valid_proposal_passes,
    test_invalid_category_normalized_to_other,
    test_valid_category_preserved,
    test_empty_title_returns_clarification,
    test_whitespace_only_title_returns_clarification,
    test_none_title_returns_clarification,
    test_past_when_text_returns_invalid,
    test_future_when_text_passes,
    test_unparseable_when_text_passes_gracefully,
    test_prayer_conflict_invalidates_task,
    test_sleep_conflict_warning_also_invalidates_task,
    test_no_conflict_with_cv_passes,
    test_context_validator_not_called_when_no_when_text,
    test_settings_valid_passes_as_proposal_only,
    test_settings_missing_target_name_fails,
    test_settings_empty_target_name_fails,
    test_settings_invalid_string_value_fails,
    test_settings_zero_value_fails,
    test_settings_negative_value_fails,
    test_task_enforces_confirmation_even_when_llm_returns_false,
    test_later_enforces_confirmation,
    test_boss_enforces_confirmation,
    test_settings_change_enforces_confirmation,
    test_validator_no_db_session_param,
    test_safe_proposal_is_always_returned,
    test_invalid_safe_proposal_downgraded_to_clarification,
    test_valid_proposal_result_has_correct_shape,
]


def main() -> None:
    async def _run_all():
        for fn in ALL_TESTS:
            await fn()

    asyncio.run(_run_all())
    print(f"\nALL {len(ALL_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
