import asyncio
from pathlib import Path

from app.services.voice_capture_safety import (
    downloaded_voice_temp_path,
    validate_voice_safety,
)


class FakeVoice:
    file_id = "voice-file-id"

    def __init__(self, *, duration: int = 10, file_size: int | None = 1024):
        self.duration = duration
        self.file_size = file_size


class FakeFile:
    file_path = "telegram/voice.ogg"


class FakeBot:
    async def get_file(self, file_id: str):
        assert file_id == "voice-file-id"
        return FakeFile()

    async def download_file(self, file_path: str, *, destination: Path):
        assert file_path == "telegram/voice.ogg"
        destination.write_bytes(b"fake voice")


class FakeMessage:
    def __init__(self):
        self.voice = FakeVoice()
        self.bot = FakeBot()


async def main():
    ok = validate_voice_safety(
        FakeVoice(duration=60, file_size=10 * 1024 * 1024),
        max_duration_sec=60,
        max_file_mb=10,
    )
    assert ok.allowed is True

    too_long = validate_voice_safety(
        FakeVoice(duration=61),
        max_duration_sec=60,
        max_file_mb=10,
    )
    assert too_long.allowed is False

    too_large = validate_voice_safety(
        FakeVoice(file_size=(10 * 1024 * 1024) + 1),
        max_duration_sec=60,
        max_file_mb=10,
    )
    assert too_large.allowed is False

    parent_after_success = None
    async with downloaded_voice_temp_path(FakeMessage()) as audio_path:
        assert audio_path.exists()
        parent_after_success = audio_path.parent
    assert parent_after_success is not None
    assert not parent_after_success.exists()

    parent_after_error = None
    try:
        async with downloaded_voice_temp_path(FakeMessage()) as audio_path:
            assert audio_path.exists()
            parent_after_error = audio_path.parent
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert parent_after_error is not None
    assert not parent_after_error.exists()

    print("PASS: voice capture safety validates limits and cleans temp files")


if __name__ == "__main__":
    asyncio.run(main())
