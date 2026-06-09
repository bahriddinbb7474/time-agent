from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class AIAdvisorSuggestion:
    enabled: bool
    action: str | None
    reason: str | None
    user_message: str


class AIAdvisorProvider(Protocol):
    async def suggest_capture_action(self, text: str) -> AIAdvisorSuggestion:
        raise NotImplementedError


class DisabledAIAdvisorProvider:
    async def suggest_capture_action(self, text: str) -> AIAdvisorSuggestion:
        return AIAdvisorSuggestion(
            enabled=False,
            action=None,
            reason=None,
            user_message="AI Advisor пока не включён.",
        )
