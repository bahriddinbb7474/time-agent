from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
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


def _normalize_usage_float(raw) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v < 0:
        return None
    return v


@dataclass(slots=True, frozen=True)
class STTUsageInfo:
    audio_seconds: float | None = None
    estimated_cost_usd: float | None = None


@dataclass(slots=True, frozen=True)
class STTResult:
    enabled: bool
    text: str | None
    user_message: str
    usage: STTUsageInfo | None = None
    request_made: bool = False


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
    def __init__(
        self, api_key: str, model: str = _DEFAULT_MODEL, language: str = ""
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language

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
        fmt = suffix.lstrip(".")  # ".ogg" → "ogg"
        payload: dict = {
            "model": self._model,
            "input_audio": {
                "data": audio_b64,
                "format": fmt,
            },
        }
        if self._language:
            payload["language"] = self._language
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
                            raw_usage = data.get("usage", {})
                            stt_usage = STTUsageInfo(
                                audio_seconds=_normalize_usage_float(raw_usage.get("seconds")),
                                estimated_cost_usd=_normalize_usage_float(raw_usage.get("cost")),
                            )
                            log.debug(
                                "STT usage: seconds=%s cost=%s",
                                stt_usage.audio_seconds,
                                stt_usage.estimated_cost_usd,
                            )
                            text = (data.get("text") or "").strip()
                            if not text:
                                return STTResult(
                                    enabled=True,
                                    text=None,
                                    user_message="Голос принял, но не смог разобрать слова.",
                                    usage=stt_usage,
                                    request_made=True,
                                )
                            return STTResult(
                                enabled=True,
                                text=text,
                                user_message="Голос расшифрован.",
                                usage=stt_usage,
                                request_made=True,
                            )
                        if resp.status in {400, 401, 403}:
                            await self._log_error_body(resp, fmt, len(audio_b64))
                            return STTResult(
                                enabled=False,
                                text=None,
                                user_message="Голос принял, расшифровка временно недоступна.",
                                request_made=True,
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
                                request_made=True,
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
            request_made=True,
        )

    async def _log_error_body(self, resp, fmt: str, b64_len: int) -> None:
        """Log HTTP 4xx error response safely — never logs key, auth header, or audio data."""
        try:
            raw = await resp.text()
        except Exception:
            log.error(
                "STT HTTP %d body unreadable model=%s format=%s",
                resp.status, self._model, fmt,
            )
            return
        try:
            body = json.loads(raw)
            err = body.get("error") or body
            if isinstance(err, dict):
                msg = str(err.get("message", ""))[:200]
                code = str(err.get("code", ""))[:50]
            else:
                msg = str(err)[:200]
                code = ""
            log.error(
                "STT HTTP %d error: message=%r code=%r model=%s format=%s b64_len=%d",
                resp.status, msg, code, self._model, fmt, b64_len,
            )
        except Exception:
            safe = raw[:300]
            if self._api_key and self._api_key in safe:
                log.error(
                    "STT HTTP %d non-JSON body suppressed (contains key) model=%s",
                    resp.status, self._model,
                )
            elif "Authorization" in safe or "Bearer" in safe:
                log.error(
                    "STT HTTP %d non-JSON body suppressed (contains auth) model=%s",
                    resp.status, self._model,
                )
            else:
                log.error(
                    "STT HTTP %d non-JSON body (first 300): %r model=%s format=%s",
                    resp.status, safe, self._model, fmt,
                )


def get_stt_provider(settings) -> STTProvider:
    provider = getattr(settings, "stt_provider", "disabled")
    if provider == "fake":
        return FakeSTTProvider()
    if provider == "openrouter":
        api_key = getattr(settings, "openrouter_api_key", "")
        model = getattr(settings, "openrouter_stt_model", _DEFAULT_MODEL)
        language = getattr(settings, "openrouter_stt_language", "")
        return OpenRouterSTTProvider(api_key=api_key, model=model, language=language)
    if provider == "groq":
        return DisabledSTTProvider(
            user_message="STT provider пока не подключён."
        )
    return DisabledSTTProvider()
