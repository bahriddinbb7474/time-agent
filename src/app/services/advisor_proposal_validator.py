"""
Stage 19.6 — Advisor proposal validator.

Validates LLM proposals before they are shown to the owner:
- category whitelist normalization
- when_text parsing via existing project parser
- past-time rejection
- prayer / sleep / protected-slot conflict check (optional ContextValidator)
- settings_change basic sanity: target_name + positive numeric target_value
- actionable proposals always have needs_confirmation=True
- invalid / unsafe proposals are downgraded to safe clarification

Does NOT write to DB.
Does NOT call any LLM provider.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.time import APP_TZ, now_tz
from app.handlers.add import parse_add_payload
from app.services.ai_advisor_provider import AdvisorProposal
from app.services.categories import KNOWN_CATEGORIES
from app.services.validation_result import ValidationStatus

log = logging.getLogger("time-agent.advisor.validator")

_ACTIONABLE_TYPES = frozenset({"task", "later", "boss", "settings_change"})


# ── Result DTO ────────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class ProposalValidationResult:
    """
    Result of validating a single AdvisorProposal.

    safe_proposal is always a valid AdvisorProposal that can be shown to the owner.
    When valid=False the safe_proposal is downgraded to a clarification.
    """
    valid: bool
    needs_clarification: bool
    reason_code: str
    user_message: str
    normalized_category: str | None
    normalized_when: datetime | None
    safe_proposal: AdvisorProposal


# ── Internal helpers ──────────────────────────────────────────────────────────


def _make_clarification_proposal(
    proposal: AdvisorProposal, *, user_message: str
) -> AdvisorProposal:
    """Return a safe clarification variant of proposal with no actionable fields."""
    return AdvisorProposal(
        intent=proposal.intent,
        proposal_type="clarification",
        title=None,
        description=None,
        category=None,
        when_text=None,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=False,
        needs_clarification=True,
        user_message=user_message,
        model=proposal.model,
        input_tokens=proposal.input_tokens,
        output_tokens=proposal.output_tokens,
        estimated_cost_usd=proposal.estimated_cost_usd,
        error=False,
    )


def _invalid(
    proposal: AdvisorProposal,
    *,
    reason_code: str,
    user_message: str,
) -> ProposalValidationResult:
    return ProposalValidationResult(
        valid=False,
        needs_clarification=True,
        reason_code=reason_code,
        user_message=user_message,
        normalized_category=None,
        normalized_when=None,
        safe_proposal=_make_clarification_proposal(proposal, user_message=user_message),
    )


def _pass_through(
    proposal: AdvisorProposal,
    *,
    needs_clarification: bool = False,
) -> ProposalValidationResult:
    return ProposalValidationResult(
        valid=True,
        needs_clarification=needs_clarification,
        reason_code="pass_through",
        user_message=proposal.user_message,
        normalized_category=None,
        normalized_when=None,
        safe_proposal=proposal,
    )


def _parse_when_text(when_text: str | None) -> datetime | None:
    """Try to extract a datetime from LLM when_text using existing project parser."""
    if not when_text:
        return None
    try:
        _, _, planned_at, _ = parse_add_payload(when_text)
        return planned_at
    except Exception:
        log.debug("Could not parse when_text=%r", when_text)
        return None


def _normalize_category(category: str | None) -> str:
    c = (category or "").strip().lower()
    return c if c in KNOWN_CATEGORIES else "other"


def _parse_settings_value(value: str | None) -> float | None:
    """Return a positive float from string, or None if invalid / not positive."""
    if not value:
        return None
    try:
        f = float((value or "").replace(",", ".").strip())
        return f if f > 0 else None
    except (ValueError, TypeError):
        return None


# ── Public validator ──────────────────────────────────────────────────────────


async def validate_advisor_proposal(
    proposal: AdvisorProposal,
    *,
    now_dt: datetime | None = None,
    context_validator: Any | None = None,
) -> ProposalValidationResult:
    """
    Validate an LLM AdvisorProposal before showing it to the owner.

    Invariants (always override LLM output):
    - help_text and none pass through unchanged.
    - clarification passes through with needs_clarification=True.
    - task/later/boss: title required, category normalized, past time rejected,
      context conflicts (prayer/sleep/protected) invalidate the proposal.
    - settings_change: target_name and positive target_value required; no DB writes.
    - Actionable proposals keep needs_confirmation=True regardless of LLM value.

    Parameters
    ----------
    proposal:
        The LLM-produced proposal to validate.
    now_dt:
        Reference time for past-time detection. Defaults to now_tz().
    context_validator:
        Optional ContextValidator instance for prayer/sleep/protected checks.
        If None, context conflict checks are skipped.
    """
    if now_dt is None:
        now_dt = now_tz()

    pt = proposal.proposal_type

    # ── Always-safe pass-through types ───────────────────────────────────────
    if pt in ("help_text", "none"):
        return _pass_through(proposal, needs_clarification=False)

    if pt == "clarification":
        return _pass_through(proposal, needs_clarification=True)

    # ── Task / Later / Boss ───────────────────────────────────────────────────
    if pt in ("task", "later", "boss"):
        return await _validate_task_like(
            proposal, now_dt=now_dt, context_validator=context_validator
        )

    # ── Settings change ───────────────────────────────────────────────────────
    if pt == "settings_change":
        return _validate_settings(proposal)

    # Fallback for any unhandled type after upstream sanitization
    return _invalid(
        proposal,
        reason_code="unhandled_proposal_type",
        user_message="Не удалось обработать предложение AI. Уточните запрос.",
    )


# ── Sub-validators ────────────────────────────────────────────────────────────


async def _validate_task_like(
    proposal: AdvisorProposal,
    *,
    now_dt: datetime,
    context_validator: Any | None,
) -> ProposalValidationResult:
    # Title must be non-empty
    title = (proposal.title or "").strip()
    if not title:
        return _invalid(
            proposal,
            reason_code="empty_title",
            user_message="Уточните название задачи.",
        )

    normalized_category = _normalize_category(proposal.category)
    normalized_when = _parse_when_text(proposal.when_text)

    # Past time
    if normalized_when is not None and normalized_when < now_dt:
        return _invalid(
            proposal,
            reason_code="past_time",
            user_message="Указанное время уже прошло. Уточните время.",
        )

    # Context conflict: prayer / sleep / protected slot (all override LLM)
    if normalized_when is not None and context_validator is not None:
        try:
            ctx_result = await context_validator.validate_event(
                start_at=normalized_when,
                duration_min=30,
                category=normalized_category,
                include_suggestion=False,
            )
            if ctx_result.status == ValidationStatus.CONFLICT:
                reason = ctx_result.reason_code or "context_conflict"
                msg = ctx_result.message or "Конфликт с расписанием. Уточните время."
                return _invalid(proposal, reason_code=reason, user_message=msg)
        except Exception:
            log.warning("Context validation failed for advisor proposal", exc_info=True)

    # Build validated safe proposal — enforce confirmation, strip settings fields
    safe = AdvisorProposal(
        intent=proposal.intent,
        proposal_type=proposal.proposal_type,
        title=title,
        description=proposal.description,
        category=normalized_category,
        when_text=proposal.when_text,
        target_name=None,
        target_value=None,
        target_unit=None,
        needs_confirmation=True,
        needs_clarification=proposal.needs_clarification,
        user_message=proposal.user_message,
        model=proposal.model,
        input_tokens=proposal.input_tokens,
        output_tokens=proposal.output_tokens,
        estimated_cost_usd=proposal.estimated_cost_usd,
        error=False,
    )

    return ProposalValidationResult(
        valid=True,
        needs_clarification=False,
        reason_code="ok",
        user_message=proposal.user_message,
        normalized_category=normalized_category,
        normalized_when=normalized_when,
        safe_proposal=safe,
    )


def _validate_settings(proposal: AdvisorProposal) -> ProposalValidationResult:
    target_name = (proposal.target_name or "").strip()
    if not target_name:
        return _invalid(
            proposal,
            reason_code="missing_target_name",
            user_message="Укажите название параметра для изменения.",
        )

    parsed_value = _parse_settings_value(proposal.target_value)
    if parsed_value is None:
        return _invalid(
            proposal,
            reason_code="invalid_target_value",
            user_message=f"Некорректное значение для '{target_name}'. Укажите положительное число.",
        )

    # Proposal only — no DB write, no actual settings mutation
    safe = AdvisorProposal(
        intent=proposal.intent,
        proposal_type="settings_change",
        title=proposal.title,
        description=proposal.description,
        category=None,
        when_text=None,
        target_name=target_name,
        target_value=proposal.target_value,
        target_unit=proposal.target_unit,
        needs_confirmation=True,
        needs_clarification=False,
        user_message=proposal.user_message,
        model=proposal.model,
        input_tokens=proposal.input_tokens,
        output_tokens=proposal.output_tokens,
        estimated_cost_usd=proposal.estimated_cost_usd,
        error=False,
    )

    return ProposalValidationResult(
        valid=True,
        needs_clarification=False,
        reason_code="ok",
        user_message=proposal.user_message,
        normalized_category=None,
        normalized_when=None,
        safe_proposal=safe,
    )
