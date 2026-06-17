"""
Stage 19.7-B — Advisor proposal presentation formatter.

Converts an AdvisorOrchestrationResult into a user-visible message and
action contract for the Telegram handler layer.

Pure: no DB, no provider calls, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.advisor_orchestrator import AdvisorOrchestrationResult
from app.services.advisor_proposal_validator import ProposalValidationResult
from app.services.ai_advisor_provider import AdvisorProposal

# ── Action name constants (stable — used by Telegram callback handlers) ────────

ACTION_CONFIRM_TASK = "confirm_task"
ACTION_CONFIRM_LATER = "confirm_later"
ACTION_CONFIRM_BOSS = "confirm_boss"
ACTION_CONFIRM_SETTINGS_CHANGE = "confirm_settings_change"
ACTION_ASK_CLARIFICATION = "ask_clarification"
ACTION_CANCEL = "cancel"


# ── Result DTO ────────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class AdvisorPresentationResult:
    """
    Formatted advisor result ready for Telegram presentation.

    safe_to_show=False signals the capture flow to hide advisor UI entirely
    (advisor disabled or no meaningful result to show).
    """
    text: str
    requires_confirmation: bool
    primary_action: str | None
    secondary_actions: list[str]
    reason_code: str
    safe_to_show: bool


# ── Internal helpers ──────────────────────────────────────────────────────────


def _skip() -> AdvisorPresentationResult:
    return AdvisorPresentationResult(
        text="",
        requires_confirmation=False,
        primary_action=None,
        secondary_actions=[],
        reason_code="advisor_disabled",
        safe_to_show=False,
    )


def _info(text: str, reason_code: str) -> AdvisorPresentationResult:
    return AdvisorPresentationResult(
        text=text,
        requires_confirmation=False,
        primary_action=None,
        secondary_actions=[],
        reason_code=reason_code,
        safe_to_show=True,
    )


def _format_task(proposal: AdvisorProposal) -> AdvisorPresentationResult:
    title = proposal.title or "Задача"
    category = proposal.category or "personal"
    parts = [f"Предлагаю задачу: {title} [{category}]"]
    if proposal.when_text:
        parts.append(f"Когда: {proposal.when_text}")
    return AdvisorPresentationResult(
        text="\n".join(parts),
        requires_confirmation=True,
        primary_action=ACTION_CONFIRM_TASK,
        secondary_actions=[ACTION_CANCEL],
        reason_code="task",
        safe_to_show=True,
    )


def _format_later(proposal: AdvisorProposal) -> AdvisorPresentationResult:
    title = proposal.title or "Задача"
    return AdvisorPresentationResult(
        text=f"Предлагаю добавить в «На потом»: {title}",
        requires_confirmation=True,
        primary_action=ACTION_CONFIRM_LATER,
        secondary_actions=[ACTION_CANCEL],
        reason_code="later",
        safe_to_show=True,
    )


def _format_boss(proposal: AdvisorProposal) -> AdvisorPresentationResult:
    title = proposal.title or "Задача"
    category = proposal.category or "personal"
    return AdvisorPresentationResult(
        text=f"Предлагаю срочную задачу (Boss): {title} [{category}]",
        requires_confirmation=True,
        primary_action=ACTION_CONFIRM_BOSS,
        secondary_actions=[ACTION_CANCEL],
        reason_code="boss",
        safe_to_show=True,
    )


def _format_settings(proposal: AdvisorProposal) -> AdvisorPresentationResult:
    name = proposal.target_name or "параметр"
    value = proposal.target_value or "?"
    unit = f" {proposal.target_unit}" if proposal.target_unit else ""
    return AdvisorPresentationResult(
        text=f"Предлагаю изменить «{name}»: {value}{unit}",
        requires_confirmation=True,
        primary_action=ACTION_CONFIRM_SETTINGS_CHANGE,
        secondary_actions=[ACTION_CANCEL],
        reason_code="settings_change",
        safe_to_show=True,
    )


def _format_by_type(
    proposal: AdvisorProposal,
    _validation: ProposalValidationResult,
) -> AdvisorPresentationResult:
    pt = proposal.proposal_type

    if pt == "help_text":
        return AdvisorPresentationResult(
            text=proposal.user_message or "Подсказка готова.",
            requires_confirmation=False,
            primary_action=None,
            secondary_actions=[],
            reason_code="help_text",
            safe_to_show=True,
        )

    if pt == "task":
        return _format_task(proposal)

    if pt == "later":
        return _format_later(proposal)

    if pt == "boss":
        return _format_boss(proposal)

    if pt == "settings_change":
        return _format_settings(proposal)

    # clarification / none / unhandled — safe question, no confirmation
    return AdvisorPresentationResult(
        text=proposal.user_message or "Уточните запрос.",
        requires_confirmation=False,
        primary_action=ACTION_ASK_CLARIFICATION,
        secondary_actions=[ACTION_CANCEL],
        reason_code=pt or "clarification",
        safe_to_show=True,
    )


# ── Public formatter ──────────────────────────────────────────────────────────


def format_advisor_result(
    result: AdvisorOrchestrationResult,
) -> AdvisorPresentationResult:
    """
    Convert an AdvisorOrchestrationResult into a presentable message.

    Pure function — no DB, no provider calls, no side effects.
    """
    if result.reason_code == "advisor_disabled":
        return _skip()

    if result.blocked_by_limit:
        return _info("Лимит AI запросов исчерпан на сегодня.", "llm_limit_exceeded")

    if result.provider_error:
        return _info("AI Advisor временно недоступен.", "provider_error")

    if result.validation_result is None:
        return _skip()

    validation = result.validation_result
    proposal = validation.safe_proposal

    if not validation.valid:
        return AdvisorPresentationResult(
            text=validation.user_message or "Уточните запрос.",
            requires_confirmation=False,
            primary_action=ACTION_ASK_CLARIFICATION,
            secondary_actions=[ACTION_CANCEL],
            reason_code=validation.reason_code,
            safe_to_show=True,
        )

    return _format_by_type(proposal, validation)
