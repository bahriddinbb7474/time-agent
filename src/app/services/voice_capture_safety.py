from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass(slots=True, frozen=True)
class VoiceSafetyResult:
    allowed: bool
    user_message: str | None = None


def validate_voice_safety(
    voice,
    *,
    max_duration_sec: int,
    max_file_mb: int,
) -> VoiceSafetyResult:
    duration = getattr(voice, "duration", None)
    if duration is not None and duration > max_duration_sec:
        return VoiceSafetyResult(
            allowed=False,
            user_message="Голос слишком длинный.",
        )

    file_size = getattr(voice, "file_size", None)
    max_file_bytes = max_file_mb * 1024 * 1024
    if file_size is not None and file_size > max_file_bytes:
        return VoiceSafetyResult(
            allowed=False,
            user_message="Голосовой файл слишком большой.",
        )

    return VoiceSafetyResult(allowed=True)


@asynccontextmanager
async def downloaded_voice_temp_path(message) -> AsyncIterator[Path]:
    with tempfile.TemporaryDirectory(prefix="time_agent_voice_") as tmp_dir:
        voice = getattr(message, "voice", None)
        bot = getattr(message, "bot", None)
        if voice is None or bot is None:
            raise RuntimeError("Voice message is incomplete")

        file_info = await bot.get_file(voice.file_id)
        file_path = getattr(file_info, "file_path", None)
        if not file_path:
            raise RuntimeError("Telegram voice file path is missing")

        destination = Path(tmp_dir) / "voice.ogg"
        await bot.download_file(file_path, destination=destination)
        yield destination
