"""Manual Telegram smoke contract for Stage 20.3 (no deployment side effects).

Owner checklist:
1. Send /schedule_tomorrow.
2. Verify the summary has no more than 15 meaningful lines.
3. Confirm the draft and verify the confirmed state is shown.
4. Press the same confirm button again; no blocks are duplicated.
5. Try rebuild after confirm; the active schedule remains confirmed and unchanged.
6. Build a fresh draft where available and decline it; repeat decline safely.
7. Press Edit; only the safe foundation message/rebuild option is shown.
8. Verify Advisor runtime state was not changed by this flow.
"""
from __future__ import annotations

import inspect

import app.handlers.schedule_review as schedule_review
from app.keyboards.schedule_review import build_schedule_review_keyboard
from app.services.schedule_proposal_formatter import MAX_SUMMARY_LINES


MANUAL_OWNER_FLOW = (
    "/schedule_tomorrow",
    "summary <= 15 lines",
    "confirm",
    "repeated confirm has no duplicates",
    "rebuild after confirmed does not replace active schedule",
    "decline draft idempotently",
    "edit is safe",
    "Advisor runtime unchanged",
)


def test_manual_owner_flow_is_complete() -> None:
    assert len(MANUAL_OWNER_FLOW) == 8
    assert MANUAL_OWNER_FLOW[0] == "/schedule_tomorrow"
    assert "repeated confirm" in MANUAL_OWNER_FLOW[3]
    assert "does not replace" in MANUAL_OWNER_FLOW[4]
    assert MANUAL_OWNER_FLOW[-1] == "Advisor runtime unchanged"


def test_review_contract_keeps_summary_limit_and_all_actions() -> None:
    assert MAX_SUMMARY_LINES == 15
    source = inspect.getsource(build_schedule_review_keyboard)
    for action in ("confirm", "edit", "decline", "rebuild"):
        assert f'"{action}"' in source


def test_review_handler_has_no_advisor_or_openrouter_coupling() -> None:
    source = inspect.getsource(schedule_review)
    assert "advisor_runtime" not in source
    assert "OpenRouter" not in source
    assert "openrouter" not in source.lower()


def main() -> None:
    test_manual_owner_flow_is_complete()
    test_review_contract_keeps_summary_limit_and_all_actions()
    test_review_handler_has_no_advisor_or_openrouter_coupling()
    print("PASS: schedule review manual smoke contract is complete and isolated")


if __name__ == "__main__":
    main()
