from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True, frozen=True)
class STTResult:
    enabled: bool
    text: str | None
    user_message: str


class STTProvider(Protocol):
    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        raise NotImplementedError


class DisabledSTTProvider:
    def __init__(
        self,
        user_message: str = "Голос принял. Расшифровка пока не включена.",
    ):
        self.user_message = user_message

    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        return STTResult(
            enabled=False,
            text=None,
            user_message=self.user_message,
        )

    async def transcribe_voice(self, voice_file_id: str) -> STTResult:
        return await self.transcribe_audio(Path(voice_file_id))


class FakeSTTProvider:
    def __init__(self, transcript: str = "personal Позвонить маме"):
        self.transcript = transcript

    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        return STTResult(
            enabled=True,
            text=self.transcript,
            user_message="Голос расшифрован.",
        )


def get_stt_provider(settings) -> STTProvider:
    provider = getattr(settings, "stt_provider", "disabled")
    if provider == "fake":
        return FakeSTTProvider()
    if provider == "groq":
        return DisabledSTTProvider(
            user_message="STT provider пока не подключён."
        )
    return DisabledSTTProvider()
