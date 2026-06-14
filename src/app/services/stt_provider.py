from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiohttp

log = logging.getLogger("time-agent.stt")

_OPENROUTER_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
_DEFAULT_MODEL = "openai/whisper-large-v3"
_TIMEOUT_SEC = 60.0
_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_SEC = 1.0
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MIME_TYPES: dict[str, str] = {
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
}


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


class OpenRouterSTTProvider:
    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model

    async def transcribe_audio(self, audio_path: Path) -> STTResult:
        if not self._api_key:
            log.error("OPENROUTER_API_KEY is not set")
            return STTResult(
                enabled=False,
                text=None,
                user_message="STT provider не настроен.",
            )

        suffix = audio_path.suffix.lower()
        if suffix not in _MIME_TYPES:
            log.warning("Unsupported audio format: %s", suffix)
            return STTResult(
                enabled=False,
                text=None,
                user_message="Формат аудио не поддерживается.",
            )

        audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        payload = {
            "model": self._model,
            "file": audio_b64,
            "file_name": audio_path.name,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SEC)
        last_exc: BaseException | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        _OPENROUTER_URL, headers=headers, json=payload
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            text = (data.get("text") or "").strip()
                            if not text:
                                return STTResult(
                                    enabled=True,
                                    text=None,
                                    user_message="Голос принял, но не смог разобрать слова.",
                                )
                            usage = data.get("usage", {})
                            log.debug(
                                "STT usage: seconds=%.2f cost=%s",
                                usage.get("seconds", 0.0),
                                usage.get("cost", "?"),
                            )
                            return STTResult(
                                enabled=True,
                                text=text,
                                user_message="Голос расшифрован.",
                            )
                        if resp.status in {400, 401, 403}:
                            log.error(
                                "STT non-retryable HTTP %d (attempt %d)",
                                resp.status,
                                attempt,
                            )
                            return STTResult(
                                enabled=False,
                                text=None,
                                user_message="Голос принял, расшифровка временно недоступна.",
                            )
                        if resp.status in _RETRYABLE_STATUSES:
                            last_exc = RuntimeError(f"HTTP {resp.status}")
                            log.warning(
                                "STT attempt %d/%d HTTP %d, retrying",
                                attempt,
                                _MAX_ATTEMPTS,
                                resp.status,
                            )
                        else:
                            log.error("STT unexpected HTTP %d", resp.status)
                            return STTResult(
                                enabled=False,
                                text=None,
                                user_message="Голос принял, расшифровка временно недоступна.",
                            )
            except asyncio.TimeoutError as exc:
                last_exc = exc
                log.warning("STT attempt %d/%d timeout", attempt, _MAX_ATTEMPTS)
            except (aiohttp.ClientConnectorError, aiohttp.ServerConnectionError) as exc:
                last_exc = exc
                log.warning(
                    "STT attempt %d/%d connection error: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    type(exc).__name__,
                )

            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SEC)

        log.error("STT all %d attempts failed: %s", _MAX_ATTEMPTS, last_exc)
        return STTResult(
            enabled=False,
            text=None,
            user_message="Голос принял, расшифровка временно недоступна.",
        )


def get_stt_provider(settings) -> STTProvider:
    provider = getattr(settings, "stt_provider", "disabled")
    if provider == "fake":
        return FakeSTTProvider()
    if provider == "openrouter":
        api_key = getattr(settings, "openrouter_api_key", "")
        model = getattr(settings, "openrouter_stt_model", _DEFAULT_MODEL)
        return OpenRouterSTTProvider(api_key=api_key, model=model)
    if provider == "groq":
        return DisabledSTTProvider(
            user_message="STT provider пока не подключён."
        )
    return DisabledSTTProvider()
