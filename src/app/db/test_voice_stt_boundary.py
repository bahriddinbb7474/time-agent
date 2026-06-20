"""Stage 20.6-B controlled STT boundary tests; no network."""
import inspect

from app.handlers.capture import _accepted_stt_transcript, _record_stt_usage_best_effort
from app.services.stt_provider import DisabledSTTProvider, STTResult


async def main_async() -> None:
    assert _accepted_stt_transcript(
        STTResult(enabled=True, text="  owner voice text  ", user_message="ok")
    ) == "owner voice text"
    assert _accepted_stt_transcript(
        STTResult(enabled=False, text="private", user_message="disabled")
    ) is None
    assert _accepted_stt_transcript(
        STTResult(enabled=True, text="   ", user_message="empty")
    ) is None
    disabled = await DisabledSTTProvider().transcribe_audio(None)
    assert disabled.enabled is False
    assert isinstance(disabled.user_message, str) and disabled.user_message.strip()

    usage_source = inspect.getsource(_record_stt_usage_best_effort)
    assert "transcript" not in usage_source
    assert "result.text" not in usage_source


def main() -> None:
    import asyncio
    asyncio.run(main_async())
    print("PASS: voice STT boundary is controlled and usage remains technical")


if __name__ == "__main__":
    main()
