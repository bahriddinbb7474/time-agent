"""
Stage 19.4 — OpenRouterAdvisorProvider contract tests.

Verifies:
- DisabledAIAdvisorProvider safe result
- FakeAIAdvisorProvider deterministic result
- Factory routing (disabled / fake / openrouter / unknown)
- OpenRouterAdvisorProvider parses valid strict JSON
- Invalid JSON → safe error fallback
- HTTP error → safe error fallback
- Timeout → safe error fallback
- Empty API key → safe error fallback, no HTTP call
- Intent / proposal_type sanitization
- Token tracking (no prompt/response text stored)

No real HTTP calls — aiohttp.ClientSession is mocked.
No production DB.
Run: powershell -ExecutionPolicy Bypass -File scripts\\codex_python.ps1 src/app/db/test_openrouter_advisor.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_TELEGRAM_ID", "123456789")

_WIN_ZONEINFO = Path(r"C:\Program Files\Git\mingw64\share\zoneinfo")
if "PYTHONTZPATH" not in os.environ and _WIN_ZONEINFO.exists():
    os.environ["PYTHONTZPATH"] = str(_WIN_ZONEINFO)

from app.services.ai_advisor_provider import (
    AdvisorProposal,
    AdvisorRequest,
    DisabledAIAdvisorProvider,
    FakeAIAdvisorProvider,
    OpenRouterAdvisorProvider,
    _parse_proposal,
    get_ai_advisor_provider,
)

_PROVIDER = "openrouter"
_MODEL = "openai/gpt-4o-mini"
_API_KEY = "test-key-not-real"
_REQ = AdvisorRequest(text="Купить молоко", advisor_intent="capture", confidence=1.0)


# ── Mock helpers ──────────────────────────────────────────────────────────────


def _make_http_mock(status: int, json_data: dict) -> MagicMock:
    """Return a mock ClientSession that responds with given status and JSON."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)

    mock_post_ctx = MagicMock()
    mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_post_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_session_ctx


def _make_post_raises(exc: BaseException) -> MagicMock:
    """Return a mock ClientSession where post().__aenter__ raises exc."""
    mock_post_ctx = MagicMock()
    mock_post_ctx.__aenter__ = AsyncMock(side_effect=exc)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_post_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_session_ctx


def _valid_json_response(
    intent: str = "capture",
    proposal_type: str = "later",
    title: str | None = "Купить молоко",
    user_message: str = "Добавить в Later?",
    needs_confirmation: bool = True,
    needs_clarification: bool = False,
    input_tokens: int = 50,
    output_tokens: int = 30,
) -> dict:
    return {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "intent": intent,
                    "proposal_type": proposal_type,
                    "title": title,
                    "description": None,
                    "category": None,
                    "when_text": None,
                    "target_name": None,
                    "target_value": None,
                    "target_unit": None,
                    "needs_confirmation": needs_confirmation,
                    "needs_clarification": needs_clarification,
                    "user_message": user_message,
                })
            }
        }],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
        },
    }


_PATCH = "app.services.ai_advisor_provider.aiohttp.ClientSession"


# ── Sync tests ────────────────────────────────────────────────────────────────


def test_advisor_request_dataclass_fields():
    req = AdvisorRequest(text="Купить молоко", advisor_intent="capture", confidence=1.0)
    assert req.text == "Купить молоко"
    assert req.advisor_intent == "capture"
    assert req.confidence == 1.0
    print("PASS: test_advisor_request_dataclass_fields")


def test_disabled_provider_returns_unavailable_proposal():
    proposal = asyncio.run(DisabledAIAdvisorProvider().advise(_REQ))
    assert isinstance(proposal, AdvisorProposal)
    assert proposal.error is False
    assert proposal.proposal_type == "none"
    assert proposal.intent == "unknown"
    assert proposal.needs_confirmation is False
    assert proposal.model == ""
    assert proposal.input_tokens == 0
    print("PASS: test_disabled_provider_returns_unavailable_proposal")


def test_fake_provider_returns_capture_intent():
    req = AdvisorRequest(text="Записать идею", advisor_intent="capture", confidence=1.0)
    proposal = asyncio.run(FakeAIAdvisorProvider().advise(req))
    assert isinstance(proposal, AdvisorProposal)
    assert proposal.error is False
    assert proposal.intent == "capture"
    assert proposal.proposal_type == "later"
    assert proposal.needs_confirmation is True
    assert proposal.model == "fake"
    assert proposal.input_tokens == 10
    assert proposal.output_tokens == 20
    print("PASS: test_fake_provider_returns_capture_intent")


def test_fake_provider_reflects_help_intent():
    req = AdvisorRequest(text="Как пользоваться?", advisor_intent="help", confidence=1.0)
    proposal = asyncio.run(FakeAIAdvisorProvider().advise(req))
    assert proposal.intent == "help"
    print("PASS: test_fake_provider_reflects_help_intent")


def test_fake_provider_title_from_text():
    req = AdvisorRequest(text="Длинный текст для теста", advisor_intent="capture", confidence=1.0)
    proposal = asyncio.run(FakeAIAdvisorProvider().advise(req))
    assert proposal.title is not None
    assert "Длинный" in proposal.title
    print("PASS: test_fake_provider_title_from_text")


def test_factory_returns_disabled_for_disabled():
    p = get_ai_advisor_provider(SimpleNamespace(advisor_provider="disabled"))
    assert isinstance(p, DisabledAIAdvisorProvider)
    print("PASS: test_factory_returns_disabled_for_disabled")


def test_factory_returns_fake_for_fake():
    p = get_ai_advisor_provider(SimpleNamespace(advisor_provider="fake"))
    assert isinstance(p, FakeAIAdvisorProvider)
    print("PASS: test_factory_returns_fake_for_fake")


def test_factory_returns_openrouter_for_openrouter():
    p = get_ai_advisor_provider(
        SimpleNamespace(advisor_provider="openrouter", openrouter_api_key=_API_KEY)
    )
    assert isinstance(p, OpenRouterAdvisorProvider)
    print("PASS: test_factory_returns_openrouter_for_openrouter")


def test_factory_returns_disabled_for_unknown_provider():
    p = get_ai_advisor_provider(SimpleNamespace(advisor_provider="nonexistent"))
    assert isinstance(p, DisabledAIAdvisorProvider)
    print("PASS: test_factory_returns_disabled_for_unknown_provider")


def test_parse_proposal_sanitizes_invalid_intent():
    data = _valid_json_response(intent="rogue_intent")
    proposal = _parse_proposal(data, _MODEL)
    assert proposal.intent == "unknown", f"got {proposal.intent!r}"
    assert proposal.error is False
    print("PASS: test_parse_proposal_sanitizes_invalid_intent")


def test_parse_proposal_sanitizes_invalid_proposal_type():
    data = _valid_json_response(proposal_type="delete_everything")
    proposal = _parse_proposal(data, _MODEL)
    assert proposal.proposal_type == "none", f"got {proposal.proposal_type!r}"
    print("PASS: test_parse_proposal_sanitizes_invalid_proposal_type")


def test_parse_proposal_tracks_tokens():
    data = _valid_json_response(input_tokens=150, output_tokens=75)
    proposal = _parse_proposal(data, _MODEL)
    assert proposal.input_tokens == 150
    assert proposal.output_tokens == 75
    assert proposal.error is False
    print("PASS: test_parse_proposal_tracks_tokens")


def test_parse_proposal_no_prompt_text_field():
    # Verify AdvisorProposal has no prompt/response/transcript field
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(AdvisorProposal)}
    forbidden = {"prompt", "response", "transcript", "user_text", "raw_text"}
    present = field_names & forbidden
    assert not present, f"AdvisorProposal must not have private-data fields: {present}"
    print("PASS: test_parse_proposal_no_prompt_text_field")


def test_parse_proposal_empty_choices_returns_error():
    data = {"choices": [], "usage": {}}
    proposal = _parse_proposal(data, _MODEL)
    assert proposal.error is True
    print("PASS: test_parse_proposal_empty_choices_returns_error")


def test_parse_proposal_invalid_json_returns_error():
    data = {
        "choices": [{"message": {"content": "not-json-{"}}],
        "usage": {},
    }
    proposal = _parse_proposal(data, _MODEL)
    assert proposal.error is True
    print("PASS: test_parse_proposal_invalid_json_returns_error")


# ── Async tests (mocked HTTP) ─────────────────────────────────────────────────


async def test_openrouter_parses_valid_json_response():
    mock_ctx = _make_http_mock(200, _valid_json_response())
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(_REQ)
    assert proposal.error is False
    assert proposal.intent == "capture"
    assert proposal.proposal_type == "later"
    assert proposal.title == "Купить молоко"
    assert proposal.needs_confirmation is True
    assert proposal.input_tokens == 50
    assert proposal.output_tokens == 30
    assert proposal.model == _MODEL
    print("PASS: test_openrouter_parses_valid_json_response")


async def test_openrouter_http_500_returns_error():
    mock_ctx = _make_http_mock(500, {})
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(_REQ)
    assert proposal.error is True
    assert proposal.model == _MODEL
    print("PASS: test_openrouter_http_500_returns_error")


async def test_openrouter_timeout_returns_error():
    mock_ctx = _make_post_raises(asyncio.TimeoutError())
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(_REQ)
    assert proposal.error is True
    assert "вовремя" in proposal.user_message or "недоступен" in proposal.user_message
    print("PASS: test_openrouter_timeout_returns_error")


async def test_openrouter_network_error_returns_error():
    mock_ctx = _make_post_raises(RuntimeError("connection refused"))
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(_REQ)
    assert proposal.error is True
    print("PASS: test_openrouter_network_error_returns_error")


async def test_openrouter_invalid_json_body_returns_error():
    mock_ctx = _make_http_mock(200, {
        "choices": [{"message": {"content": "{invalid json"}}],
        "usage": {},
    })
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(_REQ)
    assert proposal.error is True
    print("PASS: test_openrouter_invalid_json_body_returns_error")


async def test_openrouter_empty_api_key_returns_error_no_http():
    """Empty API key must return error immediately without making HTTP call."""
    call_count = 0

    def counting_session(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_http_mock(200, _valid_json_response())

    with patch(_PATCH, side_effect=counting_session):
        provider = OpenRouterAdvisorProvider(api_key="", model=_MODEL)
        proposal = await provider.advise(_REQ)

    assert proposal.error is True
    assert call_count == 0, "must not make HTTP call when API key is empty"
    print("PASS: test_openrouter_empty_api_key_returns_error_no_http")


async def test_openrouter_settings_intent_parsed():
    data = _valid_json_response(
        intent="settings",
        proposal_type="settings_change",
        title=None,
        user_message="Изменить цель воды?",
    )
    # Patch the JSON to also include target fields
    content = json.loads(
        data["choices"][0]["message"]["content"]
    )
    content["target_name"] = "Вода"
    content["target_value"] = "2"
    content["target_unit"] = "л"
    data["choices"][0]["message"]["content"] = json.dumps(content)

    mock_ctx = _make_http_mock(200, data)
    with patch(_PATCH, return_value=mock_ctx):
        provider = OpenRouterAdvisorProvider(api_key=_API_KEY, model=_MODEL)
        proposal = await provider.advise(
            AdvisorRequest(text="хочу 2 литра воды", advisor_intent="settings", confidence=1.0)
        )
    assert proposal.error is False
    assert proposal.intent == "settings"
    assert proposal.proposal_type == "settings_change"
    assert proposal.target_name == "Вода"
    assert proposal.target_value == "2"
    assert proposal.target_unit == "л"
    assert proposal.needs_confirmation is True
    print("PASS: test_openrouter_settings_intent_parsed")


# ── Runner ────────────────────────────────────────────────────────────────────


SYNC_TESTS = [
    test_advisor_request_dataclass_fields,
    test_disabled_provider_returns_unavailable_proposal,
    test_fake_provider_returns_capture_intent,
    test_fake_provider_reflects_help_intent,
    test_fake_provider_title_from_text,
    test_factory_returns_disabled_for_disabled,
    test_factory_returns_fake_for_fake,
    test_factory_returns_openrouter_for_openrouter,
    test_factory_returns_disabled_for_unknown_provider,
    test_parse_proposal_sanitizes_invalid_intent,
    test_parse_proposal_sanitizes_invalid_proposal_type,
    test_parse_proposal_tracks_tokens,
    test_parse_proposal_no_prompt_text_field,
    test_parse_proposal_empty_choices_returns_error,
    test_parse_proposal_invalid_json_returns_error,
]

ASYNC_TESTS = [
    test_openrouter_parses_valid_json_response,
    test_openrouter_http_500_returns_error,
    test_openrouter_timeout_returns_error,
    test_openrouter_network_error_returns_error,
    test_openrouter_invalid_json_body_returns_error,
    test_openrouter_empty_api_key_returns_error_no_http,
    test_openrouter_settings_intent_parsed,
]


async def main_async() -> None:
    for fn in ASYNC_TESTS:
        await fn()


def main() -> None:
    for fn in SYNC_TESTS:
        fn()
    asyncio.run(main_async())
    print("\nALL 22 TESTS PASSED")


if __name__ == "__main__":
    main()
