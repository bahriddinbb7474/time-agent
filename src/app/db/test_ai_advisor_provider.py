import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

from app.config import load_config
from app.services.ai_advisor_provider import (
    DisabledAIAdvisorProvider,
    FakeAIAdvisorProvider,
    get_ai_advisor_provider,
)


async def main():
    os.environ.pop("ADVISOR_PROVIDER", None)
    os.environ.pop("LLM_DAILY_LIMIT", None)
    cfg = load_config()
    assert cfg.advisor_provider == "disabled"
    assert cfg.llm_daily_limit == 0

    provider = get_ai_advisor_provider(cfg)
    assert isinstance(provider, DisabledAIAdvisorProvider)

    suggestion = await provider.suggest_capture_action("Запланировать встречу")
    assert suggestion.enabled is False
    assert suggestion.action is None
    assert suggestion.reason is None

    fake = get_ai_advisor_provider(SimpleNamespace(advisor_provider="fake"))
    assert isinstance(fake, FakeAIAdvisorProvider)
    fake_suggestion = await fake.suggest_capture_action("Записать идею")
    assert fake_suggestion.enabled is True
    assert fake_suggestion.action == "later"
    assert fake_suggestion.reason == "fake-test-provider"

    safe_openrouter = get_ai_advisor_provider(
        SimpleNamespace(advisor_provider="openrouter")
    )
    assert isinstance(safe_openrouter, DisabledAIAdvisorProvider)

    print("PASS: disabled AI Advisor provider makes no external call")


if __name__ == "__main__":
    asyncio.run(main())
