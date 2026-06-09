from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class STTResult:
    enabled: bool
    text: str | None
    user_message: str


class STTProvider(Protocol):
    async def transcribe_voice(self, voice_file_id: str) -> STTResult:
        raise NotImplementedError


class DisabledSTTProvider:
    async def transcribe_voice(self, voice_file_id: str) -> STTResult:
        return STTResult(
            enabled=False,
            text=None,
            user_message="Голос принял. Расшифровка пока не включена.",
        )
