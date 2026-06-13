import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from app.config import load_config
from app.services.stt_provider import (
    DisabledSTTProvider,
    FakeSTTProvider,
    get_stt_provider,
)


async def main():
    os.environ.pop("STT_PROVIDER", None)
    cfg = load_config()
    assert cfg.stt_provider == "disabled"
    assert cfg.stt_max_duration_sec == 60
    assert cfg.stt_max_file_mb == 10

    provider = get_stt_provider(cfg)
    assert isinstance(provider, DisabledSTTProvider)

    result = await provider.transcribe_audio(Path("fake.ogg"))
    assert result.enabled is False
    assert result.text is None

    fake = get_stt_provider(SimpleNamespace(stt_provider="fake"))
    assert isinstance(fake, FakeSTTProvider)
    fake_result = await fake.transcribe_audio(Path("fake.ogg"))
    assert fake_result.enabled is True
    assert fake_result.text == "personal Позвонить маме"

    safe_groq = get_stt_provider(SimpleNamespace(stt_provider="groq"))
    assert isinstance(safe_groq, DisabledSTTProvider)

    print("PASS: disabled STT provider makes no external call")


if __name__ == "__main__":
    asyncio.run(main())
