import asyncio

from app.services.stt_provider import DisabledSTTProvider


async def main():
    result = await DisabledSTTProvider().transcribe_voice("fake-file-id")
    assert result.enabled is False
    assert result.text is None
    assert result.user_message == "Голос принял. Расшифровка пока не включена."

    print("PASS: disabled STT provider makes no external call")


if __name__ == "__main__":
    asyncio.run(main())
