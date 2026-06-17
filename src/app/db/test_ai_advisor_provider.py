"""
Stage 19.4 — AI Advisor provider smoke tests (updated from Stage 19.0 stub).

Verifies factory, disabled/fake providers, and OpenRouterAdvisorProvider instance.
No real HTTP calls. No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_ai_advisor_provider.py
"""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.config import load_config
from app.services.ai_advisor_provider import (
    AdvisorProposal,
    AdvisorRequest,
    DisabledAIAdvisorProvider,
    FakeAIAdvisorProvider,
    OpenRouterAdvisorProvider,
    get_ai_advisor_provider,
)


async def main():
    # Config default: advisor_provider = "disabled"
    os.environ.pop("ADVISOR_PROVIDER", None)
    cfg = load_config()
    assert cfg.advisor_provider == "disabled", f"got {cfg.advisor_provider!r}"
    assert cfg.openrouter_advisor_model, "openrouter_advisor_model must have a default"

    # Factory → disabled
    provider = get_ai_advisor_provider(cfg)
    assert isinstance(provider, DisabledAIAdvisorProvider), type(provider)

    request = AdvisorRequest(text="Купить молоко", advisor_intent="capture", confidence=1.0)
    proposal = await provider.advise(request)
    assert isinstance(proposal, AdvisorProposal)
    assert proposal.error is False
    assert proposal.proposal_type == "none"
    assert proposal.user_message  # not empty

    # Factory → fake
    fake = get_ai_advisor_provider(SimpleNamespace(advisor_provider="fake"))
    assert isinstance(fake, FakeAIAdvisorProvider), type(fake)
    fake_proposal = await fake.advise(request)
    assert isinstance(fake_proposal, AdvisorProposal)
    assert fake_proposal.error is False
    assert fake_proposal.needs_confirmation is True
    assert fake_proposal.model == "fake"
    assert fake_proposal.intent == "capture"

    # Factory → openrouter (with empty key → provider instance, error on advise)
    openrouter_provider = get_ai_advisor_provider(
        SimpleNamespace(advisor_provider="openrouter", openrouter_api_key="")
    )
    assert isinstance(openrouter_provider, OpenRouterAdvisorProvider), type(openrouter_provider)
    # Empty API key → safe error result, no HTTP call
    no_key_proposal = await openrouter_provider.advise(request)
    assert no_key_proposal.error is True, "empty API key must return error proposal"

    # Factory → unknown provider → disabled
    fallback = get_ai_advisor_provider(SimpleNamespace(advisor_provider="unknown_xyz"))
    assert isinstance(fallback, DisabledAIAdvisorProvider), type(fallback)

    print("PASS: ai_advisor_provider factory and provider smoke tests")


if __name__ == "__main__":
    asyncio.run(main())
