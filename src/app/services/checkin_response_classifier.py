from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckinResponseClassification:
    intent: str
    normalized_text: str


class CheckinResponseClassifier:
    _INTENTS = {
        "aligned": {
            "aligned", "всё по плану", "все по плану", "всё нормально",
            "все нормально", "нормально", "ок", "ok", "hammasi reja bo'yicha",
        },
        "started": {"started", "начал", "начала", "приступил", "boshladim"},
        "defer": {"defer", "позже", "отложить", "отложи", "keyin"},
        "unknown": {
            "unknown", "не помню", "не знаю", "не помню что делал", "не знаю что делал",
            "bilmiman", "eslolmayman", "nima qilganimni eslolmayman",
            "forgot", "i don't remember", "i do not remember",
        },
        "cancel": {"cancel", "отмена", "отменить", "bekor"},
        "other_text": {"other", "другое", "другой ответ", "boshqa"},
    }

    def classify(self, value: str | None) -> CheckinResponseClassification:
        normalized = self._normalize(value)
        for intent, variants in self._INTENTS.items():
            if normalized in variants:
                return CheckinResponseClassification(intent, normalized)
        if re.search(r"[a-zа-яёʻ'0-9]", normalized):
            return CheckinResponseClassification("other_text", normalized)
        return CheckinResponseClassification("unsupported", normalized)

    @staticmethod
    def _normalize(value: str | None) -> str:
        text = (value or "").strip().lower().replace("’", "'")
        text = re.sub(r"[.!?,;:]+$", "", text)
        return " ".join(text.split())
