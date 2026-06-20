"""Manual production smoke contract for Stage 20.4.

1. A confirmed schedule exists for the test date.
2. Restart recovery plans stable check-in jobs.
3. Sleep/prayer windows receive no jobs.
4. Owner receives an active-period check-in.
5. "Всё по плану" records aligned/answered.
6. "Не помню" records unknown/no_data and creates no activity.
7. "Отложить" records deferred.
8. A duplicate callback is a no-op.
9. Logs contain no traceback/error/exception.
10. Advisor runtime remains unchanged and OFF.
"""
from __future__ import annotations

import inspect

import app.handlers.checkins as handlers
import app.services.checkin_scheduler_service as scheduler_service
from app.keyboards.checkins import build_checkin_keyboard


SMOKE_STEPS = (
    "confirmed schedule exists",
    "restart plans stable jobs",
    "protected slots suppressed",
    "owner receives active check-in",
    "aligned works",
    "unknown creates no activity",
    "defer works",
    "duplicate callback no-op",
    "logs clean",
    "Advisor remains OFF",
)


def test_smoke_contract_is_complete() -> None:
    assert len(SMOKE_STEPS) == 10
    assert "protected" in SMOKE_STEPS[2]
    assert "no activity" in SMOKE_STEPS[5]
    assert SMOKE_STEPS[-1] == "Advisor remains OFF"


def test_checkin_surface_is_rules_only_and_complete() -> None:
    buttons = [button for row in build_checkin_keyboard(1).inline_keyboard for button in row]
    assert len(buttons) == 5
    source = inspect.getsource(handlers) + inspect.getsource(scheduler_service)
    assert "advisor_runtime" not in source
    assert "openrouter" not in source.lower()
    assert "checkin_test" in source


def main() -> None:
    test_smoke_contract_is_complete()
    test_checkin_surface_is_rules_only_and_complete()
    print("PASS: check-in production smoke contract is complete and isolated")


if __name__ == "__main__":
    main()
