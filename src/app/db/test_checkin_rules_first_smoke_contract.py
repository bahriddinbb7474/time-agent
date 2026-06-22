"""Stage 20.5 manual rules-first production smoke contract."""
import inspect

import app.handlers.checkins as handlers
import app.services.checkin_response_classifier as classifier
import app.services.checkin_response_service as responses


SMOKE_STEPS = (
    "/checkin_test",
    "button aligned",
    "button unknown",
    "button defer",
    "text всё по плану",
    "text не помню",
    "text начал",
    "other then owner fact",
    "no LLM or OpenRouter",
    "logs clean",
    "unknown creates no fake activity",
    "no auto-waste",
)


def main() -> None:
    assert len(SMOKE_STEPS) == 12
    source = (
        inspect.getsource(handlers)
        + inspect.getsource(classifier)
        + inspect.getsource(responses)
    ).lower()
    assert "openrouter" not in source
    assert "advisor_runtime" not in source
    normalized = source.replace(" ", "")
    assert "owner_confirmed=true" in normalized
    assert 'waste_marked_by_owner=category=="waste"andwaste_explicit' in normalized
    print("PASS: rules-first check-in smoke contract is complete and isolated")


if __name__ == "__main__":
    main()
