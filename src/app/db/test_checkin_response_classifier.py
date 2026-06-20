"""Stage 20.5-A deterministic response classifier tests."""
from app.services.checkin_response_classifier import CheckinResponseClassifier


def main() -> None:
    classifier = CheckinResponseClassifier()
    cases = {
        "Всё по плану!": "aligned",
        "ok": "aligned",
        "нормально": "aligned",
        "начал": "started",
        "boshladim": "started",
        "позже": "defer",
        "keyin": "defer",
        "не помню": "unknown",
        "bilmiman": "unknown",
        "forgot": "unknown",
        "другое": "other_text",
        "фактически гулял с детьми": "other_text",
        "отмена": "cancel",
        "...": "unsupported",
        "": "unsupported",
    }
    for raw, expected in cases.items():
        assert classifier.classify(raw).intent == expected, raw
    print("PASS: check-in responses are classified rules-first without LLM")


if __name__ == "__main__":
    main()
