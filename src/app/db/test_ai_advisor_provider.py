import asyncio

from app.services.ai_advisor_provider import DisabledAIAdvisorProvider


async def main():
    suggestion = await DisabledAIAdvisorProvider().suggest_capture_action(
        "Запланировать встречу"
    )
    assert suggestion.enabled is False
    assert suggestion.action is None
    assert suggestion.reason is None
    assert suggestion.user_message == "AI Advisor пока не включён."

    print("PASS: disabled AI Advisor provider makes no external call")


if __name__ == "__main__":
    asyncio.run(main())
