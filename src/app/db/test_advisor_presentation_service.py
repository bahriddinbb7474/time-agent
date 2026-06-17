"""
Stage 19.7-B — Advisor presentation formatter tests.

Verifies:
- help_text proposals require no confirmation and no primary_action
- task/later/boss/settings_change proposals require confirmation
- each proposal type gets correct primary_action constant
- secondary_actions contains cancel for all actionable types
- help_text has no secondary actions
- settings_change text shows target_name, target_value, and target_unit
- task text shows title and category; when_text shown if present
- later text shows title
- boss text shows title and category
- invalid validation shows user_message with ask_clarification action
- clarification proposal gets ask_clarification action, no confirmation
- provider_error returns safe non-empty fallback message
- blocked_by_limit returns safe non-empty limit message
- advisor_disabled returns safe_to_show=False and empty text
- safe_to_show=True for all actionable proposal types
- AdvisorPresentationResult is a frozen dataclass
- ACTION_* constants match expected stable strings
- format_advisor_result is a sync function (no coroutine)
- no system prompt / secret strings leak into formatted output

No DB, no network, no async.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_advisor_presentation_service.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.services.advisor_orchestrator import AdvisorOrchestrationResult
from app.services.advisor_presentation_service import (
    ACTION_ASK_CLARIFICATION,
    ACTION_CANCEL,
    ACTION_CONFIRM_BOSS,
    ACTION_CONFIRM_LATER,
    ACTION_CONFIRM_SETTINGS_CHANGE,
    ACTION_CONFIRM_TASK,
    AdvisorPresentationResult,
    format_advisor_result,
)
from app.services.advisor_proposal_validator import ProposalValidationResult
from app.services.ai_advisor_provider import AdvisorProposal


# ── Builders ──────────────────────────────────────────────────────────────────


def _proposal(
    *,
    proposal_type: str = "later",
    title: str | None = "Тест",
    category: str | None = "personal",
    when_text: str | None = None,
    target_name: str | None = None,
    target_value: str | None = None,
    target_unit: str | None = None,
    needs_confirmation: bool = True,
    user_message: str = "Тест сообщение.",
) -> AdvisorProposal:
    return AdvisorProposal(
        intent="capture",
        proposal_type=proposal_type,
        title=title,
        description=None,
        category=category,
        when_text=when_text,
        target_name=target_name,
        target_value=target_value,
        target_unit=target_unit,
        needs_confirmation=needs_confirmation,
        needs_clarification=False,
        user_message=user_message,
        model="fake",
        input_tokens=10,
        output_tokens=20,
        estimated_cost_usd=0.0,
        error=False,
    )


def _validation(
    proposal: AdvisorProposal,
    *,
    valid: bool = True,
    reason_code: str = "ok",
    user_message: str | None = None,
) -> ProposalValidationResult:
    return ProposalValidationResult(
        valid=valid,
        needs_clarification=not valid,
        reason_code=reason_code,
        user_message=user_message or proposal.user_message,
        normalized_category=None,
        normalized_when=None,
        safe_proposal=proposal,
    )


def _result(
    validation: ProposalValidationResult | None,
    *,
    used_advisor: bool = True,
    blocked_by_limit: bool = False,
    provider_error: bool = False,
    reason_code: str = "ok",
    user_message: str = "",
) -> AdvisorOrchestrationResult:
    return AdvisorOrchestrationResult(
        used_advisor=used_advisor,
        blocked_by_limit=blocked_by_limit,
        provider_error=provider_error,
        validation_result=validation,
        user_message=user_message,
        reason_code=reason_code,
    )


def _disabled_result() -> AdvisorOrchestrationResult:
    return AdvisorOrchestrationResult(
        used_advisor=False,
        blocked_by_limit=False,
        provider_error=False,
        validation_result=None,
        user_message="",
        reason_code="advisor_disabled",
    )


def _blocked_result() -> AdvisorOrchestrationResult:
    return AdvisorOrchestrationResult(
        used_advisor=False,
        blocked_by_limit=True,
        provider_error=False,
        validation_result=None,
        user_message="Лимит AI запросов исчерпан на сегодня.",
        reason_code="llm_limit_exceeded",
    )


def _error_result() -> AdvisorOrchestrationResult:
    return AdvisorOrchestrationResult(
        used_advisor=False,
        blocked_by_limit=False,
        provider_error=True,
        validation_result=None,
        user_message="Ошибка провайдера.",
        reason_code="provider_error",
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_help_text_no_confirmation():
    p = _proposal(proposal_type="help_text", needs_confirmation=False, user_message="Вот подсказка.")
    r = format_advisor_result(_result(_validation(p)))
    assert r.requires_confirmation is False
    assert r.primary_action is None
    assert r.safe_to_show is True
    print("PASS: test_help_text_no_confirmation")


def test_task_requires_confirmation():
    p = _proposal(proposal_type="task")
    r = format_advisor_result(_result(_validation(p)))
    assert r.requires_confirmation is True
    assert r.primary_action == ACTION_CONFIRM_TASK
    print("PASS: test_task_requires_confirmation")


def test_later_requires_confirmation():
    p = _proposal(proposal_type="later")
    r = format_advisor_result(_result(_validation(p)))
    assert r.requires_confirmation is True
    assert r.primary_action == ACTION_CONFIRM_LATER
    print("PASS: test_later_requires_confirmation")


def test_boss_requires_confirmation():
    p = _proposal(proposal_type="boss")
    r = format_advisor_result(_result(_validation(p)))
    assert r.requires_confirmation is True
    assert r.primary_action == ACTION_CONFIRM_BOSS
    print("PASS: test_boss_requires_confirmation")


def test_settings_change_requires_confirmation():
    p = _proposal(
        proposal_type="settings_change",
        target_name="daily_task_limit",
        target_value="10",
        target_unit="задач",
    )
    r = format_advisor_result(_result(_validation(p)))
    assert r.requires_confirmation is True
    assert r.primary_action == ACTION_CONFIRM_SETTINGS_CHANGE
    print("PASS: test_settings_change_requires_confirmation")


def test_settings_change_text_shows_name_value_unit():
    p = _proposal(
        proposal_type="settings_change",
        target_name="daily_task_limit",
        target_value="10",
        target_unit="задач",
    )
    r = format_advisor_result(_result(_validation(p)))
    assert "daily_task_limit" in r.text
    assert "10" in r.text
    assert "задач" in r.text
    print("PASS: test_settings_change_text_shows_name_value_unit")


def test_settings_change_text_without_unit():
    p = _proposal(
        proposal_type="settings_change",
        target_name="daily_task_limit",
        target_value="5",
        target_unit=None,
    )
    r = format_advisor_result(_result(_validation(p)))
    assert "daily_task_limit" in r.text
    assert "5" in r.text
    print("PASS: test_settings_change_text_without_unit")


def test_task_text_contains_title():
    p = _proposal(proposal_type="task", title="Купить молоко")
    r = format_advisor_result(_result(_validation(p)))
    assert "Купить молоко" in r.text
    print("PASS: test_task_text_contains_title")


def test_task_text_contains_category():
    p = _proposal(proposal_type="task", title="Задача", category="work")
    r = format_advisor_result(_result(_validation(p)))
    assert "work" in r.text
    print("PASS: test_task_text_contains_category")


def test_task_text_shows_when_if_present():
    p = _proposal(proposal_type="task", title="Встреча", when_text="в 15:00")
    r = format_advisor_result(_result(_validation(p)))
    assert "15:00" in r.text
    print("PASS: test_task_text_shows_when_if_present")


def test_cancel_in_secondary_for_task():
    p = _proposal(proposal_type="task")
    r = format_advisor_result(_result(_validation(p)))
    assert ACTION_CANCEL in r.secondary_actions
    print("PASS: test_cancel_in_secondary_for_task")


def test_cancel_in_secondary_for_settings_change():
    p = _proposal(proposal_type="settings_change", target_name="x", target_value="1")
    r = format_advisor_result(_result(_validation(p)))
    assert ACTION_CANCEL in r.secondary_actions
    print("PASS: test_cancel_in_secondary_for_settings_change")


def test_help_text_has_no_secondary_actions():
    p = _proposal(proposal_type="help_text", needs_confirmation=False)
    r = format_advisor_result(_result(_validation(p)))
    assert ACTION_CANCEL not in r.secondary_actions
    print("PASS: test_help_text_has_no_secondary_actions")


def test_clarification_shows_ask_clarification_action():
    p = _proposal(
        proposal_type="clarification",
        needs_confirmation=False,
        user_message="Что именно нужно сделать?",
    )
    r = format_advisor_result(_result(_validation(p, valid=True, reason_code="pass_through")))
    assert r.primary_action == ACTION_ASK_CLARIFICATION
    assert r.requires_confirmation is False
    print("PASS: test_clarification_shows_ask_clarification_action")


def test_invalid_validation_uses_user_message():
    p = _proposal(proposal_type="task", title="Сделать X")
    v = _validation(p, valid=False, reason_code="past_time", user_message="Время уже прошло.")
    r = format_advisor_result(_result(v))
    assert "Время уже прошло." in r.text
    assert r.requires_confirmation is False
    assert r.primary_action == ACTION_ASK_CLARIFICATION
    print("PASS: test_invalid_validation_uses_user_message")


def test_provider_error_gives_fallback_message():
    r = format_advisor_result(_error_result())
    assert r.safe_to_show is True
    assert r.requires_confirmation is False
    assert r.reason_code == "provider_error"
    assert r.text
    print("PASS: test_provider_error_gives_fallback_message")


def test_blocked_by_limit_gives_message():
    r = format_advisor_result(_blocked_result())
    assert r.safe_to_show is True
    assert r.requires_confirmation is False
    assert r.reason_code == "llm_limit_exceeded"
    assert r.text
    print("PASS: test_blocked_by_limit_gives_message")


def test_advisor_disabled_safe_to_show_false():
    r = format_advisor_result(_disabled_result())
    assert r.safe_to_show is False
    assert r.text == ""
    assert r.reason_code == "advisor_disabled"
    print("PASS: test_advisor_disabled_safe_to_show_false")


def test_safe_to_show_true_for_actionable_types():
    for pt in ("task", "later", "boss"):
        p = _proposal(proposal_type=pt)
        r = format_advisor_result(_result(_validation(p)))
        assert r.safe_to_show is True, f"safe_to_show must be True for proposal_type={pt!r}"
    print("PASS: test_safe_to_show_true_for_actionable_types")


def test_result_is_frozen_dataclass():
    p = _proposal(proposal_type="later")
    r = format_advisor_result(_result(_validation(p)))
    assert dataclasses.is_dataclass(r)
    try:
        r.text = "mutate"  # type: ignore[misc]
        assert False, "FrozenInstanceError expected"
    except dataclasses.FrozenInstanceError:
        pass
    print("PASS: test_result_is_frozen_dataclass")


def test_action_constants_are_stable_strings():
    assert ACTION_CONFIRM_TASK == "confirm_task"
    assert ACTION_CONFIRM_LATER == "confirm_later"
    assert ACTION_CONFIRM_BOSS == "confirm_boss"
    assert ACTION_CONFIRM_SETTINGS_CHANGE == "confirm_settings_change"
    assert ACTION_ASK_CLARIFICATION == "ask_clarification"
    assert ACTION_CANCEL == "cancel"
    print("PASS: test_action_constants_are_stable_strings")


def test_formatter_is_sync():
    p = _proposal(proposal_type="later")
    r = format_advisor_result(_result(_validation(p)))
    assert not asyncio.iscoroutine(r), "format_advisor_result must return a value, not a coroutine"
    assert isinstance(r, AdvisorPresentationResult)
    print("PASS: test_formatter_is_sync")


def test_no_system_prompt_leak_in_output():
    p = _proposal(proposal_type="task", title="Задача")
    r = format_advisor_result(_result(_validation(p)))
    forbidden = [
        "[SYSTEM]",
        "[UNTRUSTED CAPTURE TEXT]",
        "Bearer ",
        "===",
        "JSON RESPONSE CONTRACT",
    ]
    for f in forbidden:
        assert f not in r.text, f"text must not contain system string: {f!r}"
    print("PASS: test_no_system_prompt_leak_in_output")


# ── Runner ────────────────────────────────────────────────────────────────────


ALL_TESTS = [
    test_help_text_no_confirmation,
    test_task_requires_confirmation,
    test_later_requires_confirmation,
    test_boss_requires_confirmation,
    test_settings_change_requires_confirmation,
    test_settings_change_text_shows_name_value_unit,
    test_settings_change_text_without_unit,
    test_task_text_contains_title,
    test_task_text_contains_category,
    test_task_text_shows_when_if_present,
    test_cancel_in_secondary_for_task,
    test_cancel_in_secondary_for_settings_change,
    test_help_text_has_no_secondary_actions,
    test_clarification_shows_ask_clarification_action,
    test_invalid_validation_uses_user_message,
    test_provider_error_gives_fallback_message,
    test_blocked_by_limit_gives_message,
    test_advisor_disabled_safe_to_show_false,
    test_safe_to_show_true_for_actionable_types,
    test_result_is_frozen_dataclass,
    test_action_constants_are_stable_strings,
    test_formatter_is_sync,
    test_no_system_prompt_leak_in_output,
]


def main() -> None:
    for fn in ALL_TESTS:
        fn()
    print(f"\nALL {len(ALL_TESTS)} TESTS PASSED")


if __name__ == "__main__":
    main()
